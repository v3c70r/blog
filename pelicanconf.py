from pathlib import Path
# Theme Settings
THEME = 'themes/aboutwilson'
## used for OG tags and Twitter Card data on index page
#SITEIMAGE = 'site-cover.jpg'
## used for OG tags and Twitter Card data of index page

###################################
OUTPUT_PATH = '../blog'
DEFAULT_LANG = 'en'
ARTICLE_URL = 'posts/{date:%Y}/{date:%m}/{slug}/'
ARTICLE_SAVE_AS = 'posts/{date:%Y}/{date:%m}/{slug}/index.html'
ARTICLE_LANG_URL = 'posts/{date:%Y}/{date:%m}/{slug}-{lang}/'
ARTICLE_LANG_SAVE_AS = 'posts/{date:%Y}/{date:%m}/{slug}-{lang}/index.html'
PATH = 'content'
STATIC_PATHS = ['images', 'pdfs']

# Feed generation is usually not desired when developing
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

# Custom Home page
AUTHOR = 'Qing Gu'
SITENAME = "QGU"
SITESUBTITLE = 'A personal blog.'
SITEURL = 'https://qgu.io/blog'
ABSOLUTE_URL = SITEURL
TIMEZONE = "America/Montreal"
LOCALE = ("en_CA", "fr_CA", "zh_CN")
HOME = str(Path.home())
DEFAULT_PAGINATION = 4
DEFAULT_DATE = (2012, 3, 2, 14, 1, 1)
RELATIVE_URLS = True

DEFAULT_PAGINATION = False
DISQUS_SITENAME="QGU"

