from pathlib import Path
# Theme Settings
THEME = 'themes/aboutwilson'
## used for OG tags and Twitter Card data on index page
#SITEIMAGE = 'site-cover.jpg'
## used for OG tags and Twitter Card data of index page

###################################
OUTPUT_PATH = 'output'
ARTICLE_URL = 'posts/{date:%Y}/{date:%m}/{slug}/'
ARTICLE_SAVE_AS = 'posts/{date:%Y}/{date:%m}/{slug}/index.html'
PATH = 'content'

# Custom Home page
#DIRECT_TEMPLATES = (('index', 'blog', 'tags', 'categories', 'archives'))
#PAGINATED_DIRECT_TEMPLATES = (('blog',))
#TEMPLATE_PAGES = {'home.html': 'index.html',}
#DIRECT_TEMPLATES = ['blog_index', 'category']
#PAGINATED_DIRECT_TEMPLATES = ['blog_index', 'category']
#BLOG_INDEX_SAVE_AS = 'blog/index.html'

AUTHOR = 'Qing Gu'
SITENAME = "Unit Vector"
SITESUBTITLE = 'A personal blog.'
SITEURL = 'http://tsing-gu.com/blog'
ABSOLUTE_URL = SITEURL
TIMEZONE = "America/Montreal"
LOCALE = "C"
HOME = str(Path.home())
DEFAULT_PAGINATION = 4
DEFAULT_DATE = (2012, 3, 2, 14, 1, 1)
RELATIVE_URLS = True


