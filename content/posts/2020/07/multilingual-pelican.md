Title: Multilingual post with Pelican
Slug: multilingual-pelican
Date: 2020-07-04 02:00
Lang: en
Category: pelican
Tags: blog, pelican
Author: Qing Gu
Summary: Tutorial of how this blog was build

You may have noticed that this post has multiple translations.
Pelican has multilingual support for posts. It's easy to use but requires some configurations. Here are my configurations to make it work for my blog.

### 1. Set up URLs for different languages in `pelicanconf.py` so that each language will have its own URL.

```python
DEFAULT_LANG = 'en'
ARTICLE_URL = 'posts/{date:%Y}/{date:%m}/{slug}/'
ARTICLE_SAVE_AS = 'posts/{date:%Y}/{date:%m}/{slug}/index.html'
ARTICLE_LANG_URL = 'posts/{date:%Y}/{date:%m}/{slug}-{lang}/'
ARTICLE_LANG_SAVE_AS = 'posts/{date:%Y}/{date:%m}/{slug}-{lang}/index.html'
```

### 2. Write articles in different languages with `lang` property in the meta. Simply set the property and write the post in corresponding language.

![post-meta]({static}/images/post-meta.png)

### 3. Add language selector to theme template

If needed, add language selection tags in the article template of the theme.
I'm using `aboutwilson` theme which doesn't contain the translation field. In this case, I added the links to the template of the theme in `themes/aboutwilson/templates/article.html` right below the `tags` section.

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