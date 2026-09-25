---
title: Faire tourner Qwen3.8-27B (UD-Q8_K_XL) sur 2x Radeon AI PRO R9700
slug: qwen3-8-27b-dual-r9700
date: 2026-09-22 12:00
lang: fr
category: llm
tags: llama.cpp, ROCm, R9700, Qwen3.8, LocalLLaMA
author: Qing Gu
summary: Configuration recommandée et mesures à l'appui pour faire tourner Qwen3.8-27B UD-Q8_K_XL sur deux Radeon AI PRO R9700 avec llama.cpp et ROCm.
---

> Langues : [English](/blog/2026/09/22/qwen3-8-27b-dual-r9700/) | [Francais](/blog/2026/09/22/qwen3-8-27b-dual-r9700-fr/) | [中文](/blog/2026/09/22/qwen3-8-27b-dual-r9700-cn/)

**Note :** Ceci est un point de donnée, pas une vérité absolue. C'est une configuration que j'ai mesurée sur ma machine, avec les preuves derrière chaque choix. Si vous faites tourner le même modèle sur le même type de matériel, cela devrait vous économiser un week-end de tests.

**Si vous voulez seulement la configuration, lisez cette section et arrêtez-vous. La comparaison et le raisonnement viennent après la ligne horizontale.**

## Matériel et modèle

- **CPU :** AMD EPYC 7302 (16 coeurs / 32 threads)
- **RAM :** 125 Go
- **GPU :** 2x Radeon AI PRO R9700 (gfx1201, RDNA4), 32 Go chacune (64 Go au total)
- **Interconnexion :** Chaque GPU sur PCIe 5.0 x16, sur des complexes racine différents
- **Environnement logiciel :** Noyau 6.17, ROCm 7.14
- **Framework d'inférence :** llama.cpp à la version `709fe755d` (build 11116)

**Modèle cible :** `unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL`, taille 29,3 Gio.
**Métadonnées :** 64 couches, `n_head=24`, `n_head_kv=4`, dimension de tête 256, `n_ctx_train=262144`. Le modèle supporte pas de fenêtre glissante et inclut une tête MTP (`nextn_predict_layers=1`), ce qui rend le décodage spéculatif très efficace ici.

## 1. Noyau : passthrough IOMMU

Ajoutez `amd_iommu=on iommu=pt` à la ligne de commande du noyau, puis redémarrez :

```bash
BOOT_IMAGE=... ro quiet splash amd_iommu=on iommu=pt
```

*Note : Vous n'en avez besoin que pour RCCL (étape 2). Sans cela, RCCL avertit d'un risque de blocage sur les systèmes multi-GPU.*

## 2. Compiler llama.cpp pour ROCm avec RCCL

```bash
cmake -S . -B build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DGGML_HIP_RCCL=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-rocm -j
```

**Conseils de compilation pour éviter les erreurs :**
- `GGML_HIP_ROCWMMA_FATTN` : Cette option n'existe pas dans cette révision. La passer ne fait rien (elle reste `UNINITIALIZED` dans le cache).
- `GGML_HIP_MMQ_MFMA` : Ne concerne que CDNA. Sur RDNA4, c'est sans effet ; le WMMA de gfx12 est compilé automatiquement.

## 3. Lancer l'exécution

```bash
NCCL_PROTO=Simple GGML_CUDA_ALLREDUCE=nccl \
  ./llama-server \
    -m Qwen3.8-27B-UD-Q8_K_XL.gguf \
    -ngl 99 -fa on \
    -sm tensor -ts 1,1 \
    -b 2048 -ub 1024 \
    --spec-type draft-mtp --spec-draft-n-max 3 \
    --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 \
    -c 98304 -np 1 \
    --host 0.0.0.0 --port 8080
```

La même chose via un fichier `config.ini`, si vous utilisez le mode routeur :

```ini
[*]
host = 0.0.0.0
port = 8080

+[qwen3-27b]
hf = unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL
ngl = 99
flash-attn = true
spec-type = draft-mtp
spec-draft-n-max = 3
split-mode = tensor
tensor-split = 1,1
batch-size = 2048
ubatch-size = 1024
temp = 1.0
top-p = 0.95
top-k = 20
min-p = 0.0
presence-penalty = 0.0
repeat-penalty = 1.0
```

## À quoi s'attendre

Sur un prompt d'environ 72k tokens sur cette machine :

- **Vitesse de Prefill :** environ 1450 t/s
- **Décodage avec MTP :** environ 45 t/s (très dépendant de la prévisibilité du texte)
- **Temps par passe cible :** environ 53-55 ms en contexte court, environ 62 ms à 72k de contexte
- **Variabilité :** Une acceptation élevée (code, sortie structurée) peut atteindre près de 60 t/s ; une acceptation faible (prose créative) avoisine les 40 t/s. Cette fluctuation est inhérente au décodage spéculatif.

---

*Tout ce qui suit est la preuve. Arrêtez-vous ici si vous voulez seulement la configuration.*

## Méthodologie de mesure

- **Indicateur de référence :** **Millisecondes par passe cible**, où `passes = tokens_prédits - tokens_brouillon_acceptés`. Le tokens/seconde brut est faussé par le taux d'acceptation du MTP. Les millisecondes par passe reflètent mieux la capacité matérielle.
- **Principes statistiques :** Toutes les données proviennent d'exécutions uniques. Considérez les écarts inférieurs à 5 % comme du bruit.
- **Cohérence :** Toutes les mesures utilisent `-fa on`, le split tensor et MTP `n-max=3` sur le modèle ci-dessus.

## Constat 1 : Le split Tensor bat le split Layer avec MTP

Résultats de `llama-bench` brut (sans décodage spéculatif) :
| Mode de split | Vitesse tg128 |
|---|---|
| Layer | 17,96 t/s |
| Tensor | 16,89 t/s |

Avec MTP (même prompt, départ à 9 tokens, 256 générés) :
| Mode de split | ms par passe cible | Vitesse gén. (tg) |
|---|---|---|
| Layer | 79,8 ms | 32,3 t/s |
| Tensor | 54,4 ms | 48,8 t/s |

**Conclusion :** Le split Tensor est environ 1,47x plus rapide par passe ici. La raison est que MTP transforme chaque passe cible en un petit lot (1 token bonus + jusqu'à 3 tokens brouillons). Un petit lot se parallélise sur les GPU, alors qu'un seul token est limité par la latence de l'allreduce.

**Leçon :** Mesurez toujours avec la configuration exacte que vous allez utiliser. Un benchmark sans décodage spéculatif vous aurait fait garder le split Layer, ce qui vous coûterait un tiers de votre débit de décodage.

## Constat 2 : Le P2P est réel sur ce matériel, mais sans effet sur cet AllReduce

Le matériel supporte le P2P : `amdgpu.pcie_p2p=Y`, `hipDeviceCanAccessPeer` renvoie 1 dans les deux sens. Copie directe entre pairs mesurée à ~27 Go/s contre ~14 Go/s via l'hôte.

Cependant, l'AllReduce 2-GPU intégré à llama.cpp passe par de la mémoire hôte épinglée. Le log le confirme directement :
`ggml_cuda_ar_pipeline_init: initialized AllReduce pipeline: 2 GPUs, 1024 KB chunked kernel staging + 32 MB copy-engine staging per GPU`

`GGML_CUDA_P2P=1` active la permission, mais ne change pas ce chemin. Mesuré avec split Tensor + MTP : 59,8 ms par passe avec P2P, 60,1 ms sans. Bruit pur.

## Constat 3 : RCCL booste le Prefill, mais nécessite `NCCL_PROTO=Simple`

En mode Tensor Split + MTP, pour un prompt de ~35,6k tokens :
| Type AllReduce | Vitesse Prefill | ms par passe cible |
|---|---|---|
| Interne (staging hôte) | 1088 t/s | 59,0 ms |
| RCCL (défaut) | 1446 t/s | 64,2 ms |
| RCCL (`NCCL_PROTO=Simple`) | 1444 t/s | 59,0 ms |

RCCL offre un gain de Prefill de ~33 %, mais son protocole par défaut coûte environ 10 % en décodage. `Simple` préserve le gain de Prefill et élimine la pénalité de décodage. Forcer `LL` seul est catastrophique pour le Prefill (chute à 641 t/s), ne le faites pas.

## Constat 4 : `-ub 1024` est un gain de Prefill "gratuit"

À 72k de contexte (deux exécutions chacune) :
| ubatch | Vitesse Prefill |
|---|---|
| 512 | 1331 / 1375 t/s |
| 1024 | 1438 / 1492 t/s |

Gain d'environ +8 %, débit de décodage inchangé. `-b 2048` reste optimal.

## Constat 5 : Ne quantifiez pas le cache KV ici

À 72k de contexte avec RCCL + `Simple` :
| Type KV | ms par passe cible |
|---|---|
| f16 | 63,2 ms |
| q8_0 | 68,6 ms |
| q4_0 | 67,8 ms |

Le cache KV est massif ici (~18 Go). Bien qu'il soit tentant de le réduire, le coût de déquantification dans le noyau d'attention est supérieur à la bande passante gagnée avec le Flash Attention. Gardez f16 pour une performance optimale.

## Constat 6 : `spec-draft-n-max` dépend du type de charge

Mode Tensor Split, 384 tokens générés :
| `n-max` | Vitesse prose | Accept. prose | Vitesse code | Accept. code |
|---|---|---|---|---|
| 2 | 44,0 t/s | 59,0% | 50,0 t/s | 74,8% |
| 3 | **48,7 t/s** | 54,4% | 58,3 t/s | 72,4% |
| 4 | 42,9 t/s | 38,2% | **62,4 t/s** | 69,4% |
| 5 | 46,7 t/s | 40,6% | 57,6 t/s | 55,5% |

Chaque jeton brouillon supplémentaire coûte environ 5 ms par passe. Cela n'en vaut la peine que si les jetons brouillons sont continuellement acceptés. La prose perd sa prévisibilité après 3 ; le code reste viable. Utilisez 3 pour un trafic mixte, et 4 si votre charge est principalement du code ou de la sortie structurée.

## Optimisations inefficaces
- `-DGGML_HIP_ROCWMMA_FATTN=ON` : Option inexistante dans cette révision.
- `GGML_HIP_MMQ_MFMA=ON` : CDNA uniquement.
- `GGML_CUDA_P2P=1` : Aucun effet mesurable sur le chemin AllReduce actuel.
- Quantification KV : Rend l'inférence activement plus lente.

## Réserves
- **Spécificité de l'environnement :** Les données ne représentent que ma machine ; vos chiffres varieront en fonction de votre matériel/versions (surtout le Prefill).
- **Variabilité du MTP :** Le taux d'acceptation fluctue selon le contenu, donc les tokens/seconde ne sont pas une mesure stable.
- **Différences de quantification :** Ce test est basé sur Q8. Un quant Q4 du même modèle pourrait décoder environ deux fois plus vite (car le décodage est limité par la bande passante mémoire), au prix d'une perte de qualité notable.

---

### Liste de vérification des données clés
- **Matériel :** 2x Radeon AI PRO R9700 (gfx1201)
- **Modèle :** Qwen3.8-27B-GGUF (UD-Q8_K_XL)
- **Paramètres noyau :** `amd_iommu=on iommu=pt`
- **Paramètres compilation :** `GGML_HIP=ON`, `GGML_HIP_RCCL=ON`, `AMDGPU_TARGETS=gfx1201`
- **Optimisations clés :** `NCCL_PROTO=Simple`, `GGML_CUDA_ALLREDUCE=nccl`
- **Configuration MTP :** `spec-type=draft-mtp`, `spec-draft-n-max=3`
- **Tensor Split :** `tensor-split=1,1`
- **État KV :** Conserver f16 (Pas de quantification KV)
- **Performances mesurées :** Prefill ~1450 t/s | Décodage ~45-60 t/s (selon le contenu)
