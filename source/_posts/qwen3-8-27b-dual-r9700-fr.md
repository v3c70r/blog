---
title: Faire tourner Qwen3.8-27B (UD-Q8_K_XL) sur 2x Radeon AI PRO R9700
slug: qwen3-8-27b-dual-r9700
date: 2026-09-22 12:00
lang: fr
category: llm
tags: llama.cpp, ROCm, R9700, Qwen3.8, LocalLLaMA
author: Qing Gu
summary: Configuration recommandee et mesures a l'appui pour faire tourner Qwen3.8-27B UD-Q8_K_XL sur deux Radeon AI PRO R9700 avec llama.cpp et ROCm.
---

> Langues : [English](/blog/2026/09/22/qwen3-8-27b-dual-r9700/) | [Francais](/blog/2026/09/22/qwen3-8-27b-dual-r9700-fr/) | [中文](/blog/2026/09/22/qwen3-8-27b-dual-r9700-cn/)

Ceci est un point de donnee, pas une verite absolue. C'est une configuration que j'ai mesuree sur ma machine, avec les preuves derriere chaque choix. Si vous faites tourner le meme modele sur le meme type de materiel, cela devrait vous economiser un week-end.

**Si vous voulez seulement la configuration, lisez cette section et arretez-vous. La comparaison et le raisonnement viennent apres la ligne horizontale.**

## Materiel et modele

- CPU : AMD EPYC 7302 (16 coeurs / 32 threads)
- RAM : 125 Go
- 2x Radeon AI PRO R9700 (gfx1201, RDNA4), 32 Go chacune, 64 Go au total
- Chaque GPU sur PCIe 5.0 x16, sur des complexes racine differents
- Noyau 6.17, ROCm 7.14
- llama.cpp a `709fe755d` (build 11116)

Modele : `unsloth/Qwen3.8-27B-GGUF:UD-Q8_K_XL`, 29,3 Gio. Metadonnees : 64 couches, `n_head=24`, `n_head_kv=4`, dimension de tete 256, `n_ctx_train=262144`, pas de fenetre glissante, et une tete MTP (`nextn_predict_layers=1`). Cette tete MTP est ce qui rend le decodage speculatif peu couteux ici.

## 1. Noyau : passthrough IOMMU

Ajoutez `amd_iommu=on iommu=pt` a la ligne de commande du noyau, puis redemarrez :

```
BOOT_IMAGE=... ro quiet splash amd_iommu=on iommu=pt
```

Vous n'en avez besoin que pour RCCL (etape 2). Sans cela, RCCL avertit d'un risque de blocage sur les systemes multi-GPU.

## 2. Compiler llama.cpp pour ROCm avec RCCL

```sh
cmake -S . -B build-rocm \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1201 \
  -DGGML_HIP_RCCL=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-rocm -j
```

Deux remarques pour ne pas gacher une recompilation :

- `GGML_HIP_ROCWMMA_FATTN` n'existe pas dans cette revision. Le passer ne fait rien (il reste `UNINITIALIZED` dans le cache, et il n'y a pas de code rocWMMA dans le chemin FA).
- `GGML_HIP_MMQ_MFMA` ne concerne que CDNA. Sur RDNA4 c'est sans effet. Le WMMA gfx12 est compile automatiquement.

## 3. Lancer

```sh
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

La meme chose en `config.ini`, si vous utilisez le mode routeur :

```ini
[*]
host = 0.0.0.0
port = 8080

[qwen3-27b]
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

## A quoi s'attendre

Sur un prompt d'environ 72k tokens sur cette machine :

- Prefill : environ 1450 t/s
- Decodage avec MTP : environ 45 t/s, tres dependant de la predictibilite du texte
- Par passe cible : environ 53-55 ms en contexte court, environ 62 ms a 72k de contexte

Si le taux d'acceptation est eleve (code, sortie structuree), vous verrez plutot 60 t/s. S'il est faible (prose creative), plutot 40. Ce n'est pas un bug, c'est le comportement du decodage speculatif.

---

Tout ce qui suit est la preuve. Arretez-vous ici si vous ne voulez que la configuration.

## Methode de mesure

- Metrique de reference : **millisecondes par passe cible**, ou `passes = tokens_predits - tokens_brouillon_acceptes`. Le tokens/seconde brut est fausse par le taux d'acceptation du MTP, qui depend du contenu. Les millisecondes par passe, non.
- Sauf mention contraire, les chiffres viennent d'une seule execution. Considerez les petits ecarts (moins de 5 %) comme du bruit.
- Toutes les executions utilisent `-fa on`, le split tensor et MTP `n-max=3`, sur le modele ci-dessus.

## Constat 1 : avec MTP, le split tensor bat le split layer. Un benchmark naif dit le contraire.

`llama-bench` brut, sans decodage speculatif :

| split | tg128 |
|---|---:|
| layer | 17,96 t/s |
| tensor | 16,89 t/s |

Avec MTP (meme prompt, depart a 9 tokens, 256 generes) :

| split | ms par passe cible | tg |
|---|---:|---:|
| layer | 79,8 | 32,3 t/s |
| tensor | 54,4 | 48,8 t/s |

Le split tensor est environ 1,47x plus rapide par passe ici. La raison : MTP transforme chaque passe cible en un petit batch (1 token bonus plus jusqu'a 3 tokens brouillon). Un petit batch se parallelise sur les GPU ; un seul token non, et la latence de l'allreduce domine alors.

Lecon : mesurez avec l'environnement exact que vous utiliserez. Un benchmark sans decodage speculatif vous aurait dit de garder le split layer, ce qui vous couterait un tiers de votre debit de decodage.

Confession : ma premiere comparaison MTP avait oublie de passer `-sm`, donc elle comparait layer avec lui-meme et "confirmait" layer. Passez les flags, verifiez le log, et si deux configurations donnent des chiffres identiques, soupconnez votre harnais avant de soupconner le materiel.

## Constat 2 : le P2P est bien reel sur ce materiel, mais sans effet sur cet allreduce

Le materiel le supporte : `amdgpu.pcie_p2p=Y`, `hipDeviceCanAccessPeer` renvoie 1 dans les deux sens, et une copie directe entre pairs mesure environ 27 Go/s contre environ 14 Go/s pour une copie passee par l'hote.

Mais l'allreduce 2 GPU integre a llama.cpp passe par de la memoire hote epinglee. Le log le dit :

```
ggml_cuda_ar_pipeline_init: initialized AllReduce pipeline: 2 GPUs,
1024 KB chunked kernel staging + 32 MB copy-engine staging per GPU
```

`GGML_CUDA_P2P=1` active l'acces pair, mais ne change pas ce chemin. Mesure avec split tensor + MTP : 59,8 ms par passe avec P2P, 60,1 ms sans. Du bruit. RCCL choisit aussi son propre transport, et y desactiver le P2P ne change presque rien.

Si vous compilez avec RCCL, faites le changement `iommu=pt`. Sinon, le P2P est un reglage que vous pouvez ignorer.

## Constat 3 : RCCL aide beaucoup le prefill, mais seulement avec `NCCL_PROTO=Simple`

C'est celui qui m'a surpris. Split tensor + MTP, prompt d'environ 35,6k tokens :

| allreduce | prefill | ms par passe cible |
|---|---:|---:|
| interne (staging hote) | 1088 t/s | 59,0 |
| RCCL, defaut | 1446 t/s | 64,2 |
| RCCL, `NCCL_PROTO=Simple` | 1444 t/s | 59,0 |

RCCL donne +33 % de prefill, mais sa selection de protocole par defaut coute environ 10 % en decodage. `Simple` garde le gain de prefill et supprime la penalite de decodage. Forcer `LL` seul est catastrophique pour le prefill (641 t/s), ne le faites pas.

J'ai aussi teste les listes explicites (`Simple`, `LL128`, `Simple,LL128`, `Simple,LL,LL128`). Des que la liste contient `Simple` ou `LL128`, elles sont toutes a environ 1 ms les unes des autres. Prenez `Simple` et passez a autre chose.

## Constat 4 : `-ub 1024` est un gain de prefill gratuit

A 72k de contexte, deux executions chacune :

| ubatch | prefill |
|---|---:|
| 512 | 1331 / 1375 t/s |
| 1024 | 1438 / 1492 t/s |

Environ +8 %, decodage inchange. `-b 2048` reste.

## Constat 5 : ne quantifiez pas le cache KV ici

A 72k de contexte avec RCCL + `Simple` :

| type KV | ms par passe cible |
|---|---:|
| f16 | 63,2 |
| q8_0 | 68,6 |
| q4_0 | 67,8 |

Le cache KV est gros ici : `2 * 64 couches * 1024 * 2 octets` = 256 Ko par token, soit 18 Go a 72k. C'est tentant de le reduire. Mais avec le flash attention, le cout de dequantification dans le noyau d'attention est superieur a la bande passante economisee. Gardez f16.

## Constat 6 : `spec-draft-n-max` depend de la charge de travail

Split tensor, 384 tokens generes :

| `n-max` | prose t/s | accept. prose | code t/s | accept. code |
|---:|---:|---:|---:|---:|
| 2 | 44,0 | 59,0% | 50,0 | 74,8% |
| 3 | **48,7** | 54,4% | 58,3 | 72,4% |
| 4 | 42,9 | 38,2% | **62,4** | 69,4% |
| 5 | 46,7 | 40,6% | 57,6 | 55,5% |

Chaque token brouillon supplementaire coute environ 5 ms par passe. Cela ne vaut le coup que si les tokens continuent d'etre acceptes. La prose n'est pas assez previsible au-dela de 3. Le code si. Gardez 3 pour un trafic mixte, utilisez 4 si votre charge est surtout du code ou de la sortie structuree.

## Ce qui n'a rien change

- `-DGGML_HIP_ROCWMMA_FATTN=ON` : option inexistante dans cette revision.
- `GGML_HIP_MMQ_MFMA=ON` : CDNA uniquement.
- `GGML_CUDA_P2P=1` : aucun effet mesurable avec l'un ou l'autre allreduce.
- Quantification du KV : activement plus lente.

## Reserves

- Une machine, un modele, une compilation. Vos chiffres differeront, surtout le prefill.
- L'acceptation MTP depend du contenu, donc les tokens/seconde varient beaucoup selon le prompt.
- La plupart des chiffres sont des executions uniques. Les ecarts sous 5 % ne sont pas significatifs.
- Les chiffres de decodage dependent de la quantification du modele. Ici c'est du Q8. Un quant Q4 du meme modele decodera environ deux fois plus vite, car le decodage est limite par la bande passante memoire, au prix d'une certaine perte de qualite.

Si vous reproduisez ceci et obtenez des chiffres differents, j'aimerais le savoir.
