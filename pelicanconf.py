from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from climbs_data import load_climbs, load_person_climbs, pretty_date

AUTHOR = 'Lisa, Paul'
SITENAME = 'Lockerflockig'
SITEURL = ""

THEME = "themes/eleven-pelican-theme"
THEME_TEMPLATES_OVERRIDES = ["templates"]

SUMMARY_MAX_LENGTH = 0
ELEVEN_LOGO = "images/logo.jpeg"
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

FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

LINKS = (
    ("Out adventure blog <br/>", ""),
    ("Lisa's sends", "pages/lisa-sends.html"),
    ("Paul's sends", "pages/paul-sends.html"),
)

DEFAULT_PAGINATION = False

TEMPLATE_PAGES = {
    "lisa-sends.html": "pages/lisa-sends.html",
    "paul-sends.html": "pages/paul-sends.html",
}

JINJA_GLOBALS = {
    "load_climbs": load_climbs,
    "load_person_climbs": load_person_climbs,
    "pretty_date": pretty_date,
}
