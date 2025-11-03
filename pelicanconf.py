AUTHOR = 'Lisa, Paul'
SITENAME = 'Lockerflockig'
SITEURL = ""

THEME = "themes/eleven-pelican-theme"
SUMMARY_MAX_LENGTH = 0
ELEVEN_LOGO="images/logo.jpeg"
SHOW_BANNER = True

PATH = "content"
PAGE_PATHS = ['pages']
ARTICLE_PATHS = ['articles']

TIMEZONE = 'Europe/Rome'

DEFAULT_LANG = 'en'

PLUGINS = [
    'neighbors',
    'minchin.pelican.plugins.summary',
]

# Feed generation is usually not desired when developing
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

# Blogroll
LINKS = (
        ("Out adventure blog <br/>",""),
        ("Lisa's sends", "pages/lisa-sends.html"),
        ("Paul's sends", "pages/paul-sends.html"),
         )


DEFAULT_PAGINATION = False

# Uncomment following line if you want document-relative URLs when developing
# RELATIVE_URLS = True
