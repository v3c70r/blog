---
title: Visual Assist like keybindings for Vim
slug: vim-vs-keybinding
date: 2020-07-13 11:59
lang: en
category: vim
tags: vim, ctags, cscope, visual assist, tool
author: Qing Gu
summary: How to use Visual Assist keybindings for Vim
---


# Visual Assist like keybindings for Vim

After developing in Visual Studio at work for a few years, I have been spoiled by the convenience of a few shortcuts to navigate around the code. When I get back to Vim at home, my muscle memory can't help to press the same key combinations. To help this situation a little bit, I have created to some of the commonly used shortcuts in Vim to map to the same functionality as Visual Assist. It works surprisingly good so far. Here are a set of key bindings I'll set up in this post:

|Key | Function|
|-|-|
|Shift-Alt-g| Open a file|
|Shift-Alt-o| Search for a symbol|
|Alt-m|Jump to symbols in current file|
|Shift-Alt-f| Search for all references|
|Alt-o|Jump between headers and sources

## TL;DR
1. Install Ctags and Cscope
2. Install CtrlP plugin for Vim
3. Generate tags in the root folder of the project
```bash
ctags -R .
```
4. Generate Cscope database in the root folder of the project
```bash
cscope -R
```
5. Setup keybindings and Cscope auto load in `vimrc`
```vim
" Visaul Assist style file and symbol search
noremap <a-s-s> :CtrlPTag<cr>
noremap <a-s-o> :CtrlP<cr>
noremap <a-m> :CtrlPBufTag<cr>
if has("cscope")
  set cscopetag
  set csto=0
  set tags=./tags,tags;/
  set cscopeverbose
  " add any cscope database in current directory
  if filereadable("cscope.out")
    cs add cscope.out
    " else add the database pointed to by environment variable
  elseif $CSCOPE_DB != ""
    cs add $CSCOPE_DB
  endif
  nmap <a-s-f> :cs find s <C-R>=expand("<cword>")<CR><CR>
endif
```
## Open Files with CtrlP

* Required plugin/executable: [CtrlP](https://github.com/ctrlpvim/ctrlp.vim)

CtrlP  is a great plugin to search files in folder, to use the keybinding, simply map the key combinations to invoke CtrlP command:
```vim
noremap <a-s-o> :CtrlP<cr>
```

![img](https://i.imgur.com/lmx0zxQ.gif)

## Look for Symbols with CtrlP's Symbol Search

* Required plugin/executable: [CtrlP](https://github.com/ctrlpvim/ctrlp.vim), [Ctags](http://ctags.sourceforge.net/)

CtrlP works great with Ctags by invoking `CtrlPTag`. It works simply with another key mapping:
```vim
noremap <a-s-s> :CtrlPTag<cr>
```
Note that tag file is needed to make it work properly, to generate tags file, simply run the ctags at the root folder of the :
```bash
ctags -R .
```
![img](https://i.imgur.com/wACdCIW.gif)

## Jump to a symbol in current file

* Required plugin/executable: [CtrlP](https://github.com/ctrlpvim/ctrlp.vim), [Ctags](http://ctags.sourceforge.net/)

Similarly to search for symbols, searching for symbols within the file can be done with `CtrlPBufTag` command, adding the following key mapping to `vimrc`:
```vim
noremap <a-m> :CtrlPBufTag<cr>
```
![img](https://i.imgur.com/m2o0BBD.gif)

## Find all References with Cscope

* Required plugin/executable: [Cscope](http://cscope.sourceforge.net/)

### Generate Cscope database file

We'll need to generate a database file for Cscope with command `cscope –Rb` at the root folder of the project. It will generate `cscope.out` database that will be used later in Vim.

### Using Cscope in Vim

Cscope is a built-in feature for Vim. After generating the Cscope database, we can add it to Vim with `:cs add cscope.out`. Now, the cscope should be good to go. To search for all the references of a symbol, simply type `:cs find s [symbol]`
![img](https://i.imgur.com/fZeDYAQ.gif)

### Keybindings

Typing all the command with Cscope is too much work, a few keybindings has been provided by the [Cscope tutorial](http://cscope.sourceforge.net/cscope_vim_tutorial.html), with the vim file provided, you can simply search the references with `Ctrl+\ s` with the symbol under the cursor.

```vim
nmap <C-\>s :cs find s <C-R>=expand("<cword>")<CR><CR>
```

### Further optimization

Search result selection is far from optimal, we'll have to type the selection in command to jump to the specific item. It would be ideal to have something similar to *Ctrl-P*' s output selection




