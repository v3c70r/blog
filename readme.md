## Blog publish automation

This repo uses Github Action to publish blug automatically when there's a new push to this repo.

## Prerequisite

* pandoc
* npm and hexo

## Configurations

* _config.yml is the Hexo configuration file, should be copied to root folder of Hexo project.
* _next_config.yml is the next configuration file, should be copied to root of theme folder `theme/next/`.


## Scripts

There are two scripts in this repo.

* `config_hexo_next.sh` to config blog environment locally.
* `deploy_hexo_next.sh` to deploy to blog repo

## Github Action

Github Action needs to setup key pair to be able to push to target repo.

1. Generate a a pair of SSH key.
2. Copy public key to target repo (The blog repo).
3. Add private key to Secret of this repo with name `SSH_KEY`


