---
title: Faire tourner Qwen3.8-Flash-Next (UD-Q4_K_XL, MoE 125B) avec MTP sur 2x Radeon AI PRO R9700
slug: qwen3-8-flash-next-dual-r9700
date: 2026-09-27 12:00
lang: fr
category: llm
tags: llama.cpp, ROCm, R9700, Qwen3.8, MTP, LocalLLaMA
author: Qing Gu
summary: Configuration mesurée et preuves pour faire tourner le MoE Qwen3.8-Flash-Next 125B avec décodage spéculatif MTP sur deux Radeon AI PRO R9700, y compris le correctif du dépassement mémoire MTP et la stratégie de déport des experts.
---

> Langues : [English](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700/) | [Français](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700-fr/) | [中文](/blog/2026/09/27/qwen3-8-flash-next-dual-r9700-cn/)

**Note :** Ceci est un point de données, pas une vérité absolue. Ceci fait suite à mon article précédent sur Qwen3.8-27B sur la même machine. Ce modèle a une architecture différente et environ 3,5 fois plus gros, donc la plupart des réglages précédents ne s'appliquent pas. Je partage ici les configurations que j'ai mesurées et les preuves derrière chaque choix.

**Si vous voulez seulement la configuration, lisez cette section et arrêtez-vous. La comparaison et le raisonnement viennent après la ligne horizontale.**

## Matériel et modèle

Même machine que l'article précédent :

- **CPU :** AMD EPYC 7302 (16 coeurs / 32 threads)
- **RAM :** 125 Go
- **GPU :** 2x Radeon AI PRO R9700 (gfx1201, RDNA4), 32 Go chacune (64 Go au total)
- **Interconnexion :** Chaque GPU sur PCIe 5.0 x16, sur des complexes racine différents
- **Environnement logiciel :** Noyau 6.17, ROCm 7.14
- **Framework d'inférence :** llama.cpp sur la branche `qwen4exp/mtp` à la version `6fcaa16f4` (build 11098), compilé pour ROCm

**Modèle cible :** `unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL`, taille 103,7 Gio (111,3 Go). C'est un MoE de 125B.
**Tête MTP :** `unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf`, 2,6 Go.

**Métadonnées :** architecture `qwen4exp`, 48 blocs. Un bloc sur quatre est une couche d'attention complète (12 au total) ; les 36 autres sont des couches d'attention linéaire / SSM. `n_embd=2560`, `n_head=24`, `n_head_kv=2`, dimension clé/valeur 256, `n_ctx_train=262144`. 512 experts par couche, 10 actifs, FFN d'expert 640, FFN d'expert partagé 640. Les couches d'attention complète utilisent un indexeur par blocs (`attention.indexer.top_k=2048`) avec un ratio de compression de 4, donc l'attention longue est bornée par le top-k et non par la longueur brute du contexte. Le modèle fournit une tête MTP (`nextn_predict_layers=1`).

## 1. Framework : il faut la branche MTP, pas llama.cpp standard

llama.cpp standard (testé à `709fe755d`, build 11116) expose `--spec-type draft-mtp`, mais n'a pas de graphe MTP pour l'architecture `qwen4exp`. La tête MTP partagée échoue même à se charger :

```text
E llama_model_load: error loading model: check_tensor_dims: tensor 'token_embd.weight' not found
```

La tête partagée omet volontairement l'embedding des tokens et la projection de sortie, et les emprunte au modèle cible. Le code principal n'a pas d'emprunt de tenseurs entre modèles, donc la tête partagée ne peut pas être chargée du tout. Compilez plutôt la branche :

```bash
git clone --branch qwen4exp/mtp https://github.com/danielhanchen/llama.cpp
cmake -S llama.cpp -B llama.cpp/build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build llama.cpp/build-rocm -j
```

**Note :** Ma compilation de la branche est en `GGML_HIP_RCCL=OFF`. Les conclusions sur le tensor split et RCCL de l'article précédent ne s'appliquent de toute façon pas ici : le tensor split n'est pas implémenté pour cette architecture (voir Constat 3).

## 2. Télécharger le modèle et la tête MTP partagée

```bash
hf download unsloth/Qwen3.8-Flash-Next-GGUF \
  --local-dir unsloth/Qwen3.8-Flash-Next-GGUF \
  --include "UD-Q4_K_XL/*" \
  --include "*mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf*"
```

La tête arrive dans le sous-dossier `MTP/`. La découverte automatique ne cherche pas dans ce dossier, donc passez toujours `-md` explicitement.

## 3. Lancer l'exécution

```bash
./llama-server \
  -hf unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL \
  -md unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  --spec-type draft-mtp --spec-draft-n-max 3 \
  -ngl 999 \
  -ot "blk\.(0|1|2|3|4|5|6|7|8|9|10)\.ffn_(up|down|gate|gate_up)_(ch|)exps=CPU,blk\.(37|38|39|40|41|42|43|44|45|46|47)\.ffn_(up|down|gate|gate_up)_(ch|)exps=CPU" \
  -c 131072 -np 1 \
  -b 2048 -ub 1024 -t 24 \
  -fa on --load-mode none --no-mmproj \
  --host 0.0.0.0 --port 8080
```

Les deux motifs `-ot` gardent les experts routés des couches 0-10 et 37-47 en RAM et mettent tout le reste sur les GPU. Cela répartit les experts résidant en RAM sur des couches basses et hautes, pour que les deux cartes finissent avec un nombre similaire de couches d'experts sur GPU.

Si vous voulez simplement que le modèle démarre, avec un petit contexte, le seul changement qui corrige l'erreur MTP de dépassement mémoire est une marge de fit plus grande :

```bash
./llama-server \
  -hf unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL \
  -md unsloth/Qwen3.8-Flash-Next-GGUF/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  --spec-type draft-mtp --spec-draft-n-max 3 \
  --fit-target 4096 \
  --host 0.0.0.0 --port 8080
```

## Performances attendues

Sur cette machine, à 131072 de contexte, en échantillonnage glouton :

- **Vitesse de prefill :** ~474 t/s avec `-ub 1024`
- **Décodage avec MTP :** ~34 t/s
- **Taux d'acceptation MTP :** ~0,54, longueur acceptée moyenne ~2,6
- **VRAM utilisée :** ~59,8 Go sur 64 Go
- **RAM utilisée :** ~44 Go

Le prefill d'un prompt complet de 128k prend environ 4,5 minutes. La vitesse de décodage est assez plate avec le contexte, car 36 couches sur 48 sont de l'attention linéaire et les couches d'attention complète sont bornées par le top-k de l'indexeur.

---

*Les sections suivantes contiennent les preuves techniques et le raisonnement.*

## Méthodologie

- **Métrique de référence :** tokens/seconde en prefill (pp) et en décodage (tg), plus le taux d'acceptation MTP et la longueur moyenne acceptée rapportés par le serveur.
- **Échantillonnage :** glouton (`temperature=0`) pour toutes les mesures. Le débit du décodage spéculatif dépend de la prévisibilité du texte, donc la température 0 élimine une source de variance. L'acceptation diffère quand même entre configurations, car un placement GPU/CPU différent change légèrement les résultats flottants et donc le texte généré.
- **Prompt :** sauf mention contraire, un prompt de 6669 tokens et 400 tokens générés.
- **Principe statistique :** mesures uniques. Les écarts sous 5 % sont considérés comme du bruit.
- **Cohérence :** `-c 131072 -np 1`, `-fa on` et `--no-mmproj` pour toutes les mesures.

## Constat 1 : la tête MTP partagée dépasse la mémoire avec le fit par défaut

La configuration par défaut de la fiche du modèle échoue au chargement :

```text
E ggml_backend_cuda_buffer_type_alloc_buffer: allocating 2647.04 MiB on device 1: cudaMalloc failed: out of memory
E alloc_tensor_range: failed to allocate ROCm1 buffer of size 2775623424
E llama_model_load: error loading model: unable to allocate ROCm1 buffer
```

Deux choses se combinent :

1. `--fit` dimensionne le modèle principal avec une marge par défaut de 1024 Mio par carte, donc les deux cartes sont remplies à moins de 1 Gio près.
2. `--fit` ne peut pas tenir compte de la tête MTP. Mesurer un contexte supplémentaire exige le contexte cible, qui n'existe pas encore, donc le fit journalise `qwen4exp requires ctx_other to be set (this warning is normal during memory fitting)` et dimensionne sans elle.

La tête a besoin de 2,6 Go mais seulement ~1 Go était réservé. Augmenter la marge corrige le problème :

```bash
--fit-target 4096
```

Le chargement passe alors proprement. Avec `-c 32768` cela passe aussi, car un contexte explicite permet au fit de déplacer plus de couches vers le CPU pour faire de la place.

## Constat 2 : MTP vaut le coup, et llama.cpp standard ne peut pas le fournir

Même prompt, même déport (24 couches d'experts en RAM, `--load-mode none`) :

| Compilation | MTP | Prefill | Décodage | Acceptation |
|---|---|---|---|---|
| llama.cpp standard `709fe755d` | non | 368 t/s | 23,7 t/s | - |
| branche `qwen4exp/mtp` | non | 368 t/s | 23,4 t/s | - |
| branche `qwen4exp/mtp` | oui, `n-max 3` | 351 t/s | 33,8 t/s | 0,54 |

Sans MTP, les deux compilations sont identiques. Avec MTP, la branche est environ 1,45x plus rapide en décodage. Il n'y a donc aucune raison de faire tourner ce modèle sans MTP ici, ni d'utiliser llama.cpp standard.

## Constat 3 : le tensor split n'est pas implémenté pour cette architecture

L'article précédent montrait que le tensor split battait le layer split avec MTP. Cela ne s'applique pas ici :

```text
E llama_model_load: error loading model: LLAMA_SPLIT_MODE_TENSOR not implemented for architecture 'qwen4exp'
```

Le layer split (avec les surcharges `-ot` par tenseur) est la seule option. C'est aussi pourquoi le réglage RCCL et P2P de l'article précédent n'est pas pertinent sur ce modèle.

## Constat 4 : ce modèle ne rentre pas, donc le déport des experts domine

Tailles exactes des tenseurs des fragments UD-Q4_K_XL :

| Catégorie | Taille |
|---|---|
| Experts routés | 71,7 Gio |
| Table d'embedding n-gram PLE | 26,8 Gio |
| Attention | 2,4 Gio |
| Projection de sortie | 0,6 Gio |
| Embedding des tokens | 0,6 Gio |
| SSM | 0,6 Gio |
| Hyper-connexions | 0,3 Gio |
| Experts partagés | 0,2 Gio |
| Indexeur | 0,04 Gio |
| **Total** | **103,7 Gio** |

Les experts routés seuls dépassent les 64 Go de VRAM. La table PLE est lue paresseusement et reste en RAM. La stratégie est donc l'inverse du 27B : garder tout sauf les experts routés sur le GPU (`-ngl 999`), et garder autant de couches d'experts en RAM que nécessaire.

| Couches d'experts en RAM | Prefill | Décodage | VRAM |
|---|---|---|---|
| 48 (toutes) | 170 t/s | 24,9 t/s | 17 Go |
| 24 | 280 t/s | 32,9 t/s | 55 Go |
| 22 | 474 t/s | 34,1 t/s | 60 Go |
| 20 | 490 t/s | 34,5 t/s | 63 Go |

La ligne à 20 couches tient avec moins de 1 Gio de marge, ce qui est trop fragile au quotidien. Je me suis arrêté à 22.

## Constat 5 : `--n-cpu-moe` concentre les experts sur un seul GPU

La façon évidente de garder en RAM les experts des N premières couches est `--n-cpu-moe N`. Ne l'utilisez pas ici. Comme le découpage se fait par couche, mettre les couches 0-19 en RAM laisse toutes les couches d'experts GPU aux couches 20-47, et celles-ci sont assignées au second GPU :

```text
E alloc_tensor_range: failed to allocate ROCm1 buffer of size 39613846784
```

C'est une seule allocation de 37,8 Gio sur une carte. Répartir la surcharge sur des couches basses et hautes équilibre les deux cartes et se charge sans problème. C'est le motif `-ot` de la section d'exécution.

## Constat 6 : `--load-mode none` aide les experts résidant en RAM

Même déport et même génération, seul le mode de chargement change :

| Mode de chargement | Prefill | Décodage |
|---|---|---|
| mmap (par défaut) | 280 t/s | 32,9 t/s |
| none | 327 t/s | 36,4 t/s |

Les experts en RAM sont lus à chaque token, donc éviter les défauts de page pour eux est un vrai gain : environ +17 % en prefill et +11 % en décodage. Le loader l'indique même :

```text
W llama_model_loader: tensor overrides to CPU are used with mmap enabled
  - consider using --load-mode none for better performance
```

Le coût est un démarrage plus lent, car le modèle est lu en RAM au lieu d'être mappé.

## Constat 7 : `-ub 1024` pour le prefill, `n-max 2` ou `3` pour le décodage

Pour le prefill, avec 22 couches d'experts en RAM :

| ubatch | Prefill |
|---|---|
| 512 | 351 t/s |
| 1024 | 398 t/s |
| 2048 | 386 t/s |

1024 est l'optimum. Le prefill est le coût dominant pour un prompt de 128k, donc cela vaut la peine de l'optimiser.

Pour le décodage, avec 24 couches d'experts en RAM :

| `n-max` | Décodage | Acceptation | Longueur moyenne |
|---|---|---|---|
| 2 | 33,0 t/s | 0,669 | 2,33 |
| 3 | **33,8 t/s** | 0,542 | 2,62 |
| 4 | 28,8 t/s | 0,415 | 2,65 |
| 5 | 26,7 t/s | 0,359 | 2,78 |

Au-delà de 3, l'acceptation s'effondre alors que le coût du draft continue d'augmenter, car la tête MTP est elle-même une couche MoE à 512 experts et chaque draft supplémentaire est un forward complet en plus. Utilisez 2 pour du trafic mixte et 3 quand la sortie est prévisible. C'est la même forme que sur le 27B, mais la chute est plus raide ici.

## Constat 8 : 24 threads, pas 32

Avec 24 couches d'experts en RAM :

| Threads | Décodage |
|---|---|
| 16 | 33,3 t/s |
| 24 | 33,8 t/s |
| 32 | 20,9 t/s |

32 threads (SMT) est bien pire. 24 est un petit gain par rapport au 16 par défaut.

## Optimisations sans effet

- Tensor split : non implémenté pour `qwen4exp`.
- RCCL : absent de la compilation de la branche MTP, et sans intérêt sans tensor split.
- `--n-cpu-moe N` : concentre les experts GPU sur une carte et dépasse la mémoire.
- `n-max` 4 ou 5 : débit de décodage inférieur à 2 ou 3.
- Plus de 24 threads : la contention SMT nuit.
- Utiliser la compilation llama.cpp standard : pas de MTP pour cette architecture.

## Réserves

- **Spécificité de l'environnement :** Les données reflètent ma machine et mes versions. Le prefill en particulier variera.
- **Mesures uniques :** Les écarts sous 5 % sont du bruit. Quand je n'ai pas pu séparer deux configurations, je l'ai dit.
- **Variabilité MTP :** L'acceptation dépend du contenu, donc les tokens/seconde ne sont pas une métrique stable.
- **Stabilité de la branche :** La branche `qwen4exp/mtp` est la pull request en cours de revue. Les options et le comportement peuvent changer avant son intégration.
- **Non testé :** La quantification du cache KV et l'affinité CPU des threads. J'ai gardé le KV en f16 car son empreinte est faible ici (seulement 12 couches sur 48 portent un KV complet), donc le quantifier ne semblait pas valoir le risque.

Si vous reproduisez ceci et obtenez d'autres chiffres, cela m'intéresse.

---

### Récapitulatif des données clés

- **Matériel :** 2x Radeon AI PRO R9700 (gfx1201), 125 Go de RAM
- **Modèle :** Qwen3.8-Flash-Next-GGUF (UD-Q4_K_XL), 103,7 Gio
- **Tête MTP :** mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf
- **Compilation :** llama.cpp `qwen4exp/mtp` à `6fcaa16f4`, `GGML_HIP=ON`, `AMDGPU_TARGETS=gfx1201`
- **Optimisations clés :** `-ngl 999` avec experts CPU répartis via `-ot`, `--load-mode none`, `-ub 1024`, `-t 24`
- **Config MTP :** `--spec-type draft-mtp --spec-draft-n-max 3`
- **Contexte :** `-c 131072 -np 1`
- **État du KV :** f16 (non testé avec quantification)
- **Performances mesurées :** Prefill ~474 t/s | Décodage ~34 t/s | Acceptation ~0,54
