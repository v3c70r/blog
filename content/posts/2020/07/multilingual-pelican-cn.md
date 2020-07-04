Title: Pelican 发布多语言文章
Slug: multilingual-pelican
Date: 2020-07-04 02:00
Lang: 中
Category: pelican
Tags: blog, pelican
Author: Qing Gu
Summary: Tutorial of how this blog was build

你应该已经注意到这篇文章有多个语言的翻译。
Pelican 支持发布多语言文章，只需要一些简答的设置就能实现该功能。以下是我为了实现多语言支持进行的设置。

### 1. 在`pelicanconf.py`给各个语言设置相应的 URL，让每篇文章不同的语言有自己的 URL。

```python
DEFAULT_LANG = 'en'
ARTICLE_URL = 'posts/{date:%Y}/{date:%m}/{slug}/'
ARTICLE_SAVE_AS = 'posts/{date:%Y}/{date:%m}/{slug}/index.html'
ARTICLE_LANG_URL = 'posts/{date:%Y}/{date:%m}/{slug}-{lang}/'
ARTICLE_LANG_SAVE_AS = 'posts/{date:%Y}/{date:%m}/{slug}-{lang}/index.html'
```

### 2. 使用 `lang` 属性制定文章的语言。用相同的 slug 标记同一篇文章。

![post-meta]({static}/images/post-meta.png)

### 3. 将语言选项添加到主题模版中 

有些模版未提供多语言选项，比如我使用的`aboutwilson` 模版。这种情况只要将语言选项的 section 加入到模版的相应文件 `themes/aboutwilson/templates/article.html` 中就行了。 

```html
{% if article.translations %} 
<div>
    Languages:
    {% for translation in article.translations %}
    <span itemprop="translation">
        <a href="{{ SITEURL }}/{{ translation.url }}" rel="translation">{{translation.lang}}</a>
    </span>
    {% endfor %}
</div>
```