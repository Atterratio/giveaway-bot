#!/usr/bin/env python3

import abc
import configparser
import json
import logging
import multiprocessing
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from http import cookiejar
from optparse import OptionParser
from urllib.error import HTTPError

import bs4
import requests

try:
    import lxml
except:
    PARSER = "html.parser"
else:
    PARSER = "lxml"

os.chdir(os.path.dirname(__file__))

User_Agent = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:50) Gecko/20100101 Firefox/50.0'


class Error(Exception):
    def __init__(self, name, message):
        log = logging.getLogger(name)
        if not log.hasHandlers():
            formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
                                          "%Y-%m-%d %H:%M:%S")
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            log.addHandler(console)
        log.error(message)


class ParserError(Error):
    pass


class GiveawayBot:
    def __init__(self, log_level):
        self.log_level = log_level
        self.log = logging.getLogger('Bot')
        if not self.log.hasHandlers():
            formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
                                          "%Y-%m-%d %H:%M:%S")
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            self.log.addHandler(console)
        self.log.setLevel(self.log_level)

        self.config = configparser.ConfigParser()
        try:
            self.config.read_file(open("giveaway_bot.ini"))
        except FileNotFoundError:
            self.log.error("No config file. Please copy «giveaway_bot.exp» as «giveaway_bot.ini» and edit it.")
            sys.exit()

        self.harvesters = [{"name": "SteamGifts"}, {"name": "IndieGala"}]
        self.processes_logs = {}

    def start(self):
        for harvester in self.harvesters:
            enable = int(self.config[harvester['name']]['enable'])
            if enable:
                queue = multiprocessing.Queue()
                self.processes_logs.update({harvester['name']: queue})
                process = multiprocessing.Process(target=spawner, name=harvester['name'],
                                                  args=(harvester['name'], queue, self.log_level))
                process.start()

    def stop(self):
        for child in multiprocessing.active_children():
            child.terminate()

        sys.exit()


class Parser(metaclass=abc.ABCMeta):
    name = None
    verbose_name = None
    site_url = None
    check_tag = None
    check_type = None
    check_text = None
    cookies = {}
    cookies_file = None

    def __init__(self, queue, log_level):
        self.login = False
        self.log_level = log_level
        self.log = logging.getLogger(self.name)
        if not self.log.hasHandlers():
            formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
                                          "%Y-%m-%d %H:%M:%S")
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            self.log.addHandler(console)
        self.log.setLevel(log_level)

        self.config = configparser.ConfigParser()
        self.config.read_file(open("giveaway_bot.ini"))
        self.config = self.config[self.name]

        self.queue = queue

        try:
            self.user_agent = User_Agent
        except AttributeError:
            pass

        self.cookies_file = '%s.cook' % self.name

        self.cj = cookiejar.LWPCookieJar(self.cookies_file)
        try:
            self.cj.load()
        except FileNotFoundError:
            for key in self.cookies:
                self.cookies[key] = self.config[key]

            expires = datetime.now() + timedelta(days=365)
            expires = expires.timestamp()

            requests.utils.cookiejar_from_dict(self.cookies, cookiejar=self.cj, expires=expires,
                                               discard=False, rest={})

        self.session = requests.Session()
        self.session.cookies = self.cj

    def __del__(self):
        if self.login:
            self.cj.save()
        else:
            try:
                os.remove(self.cookies_file)
            except FileNotFoundError:
                pass

    def _crash(self):
        timestamp = datetime.now()
        results = {'timestamp': timestamp, 'status': 'error'}
        self.queue.put(results)

        self.log.error('Parsing %s interrupted.' % self.verbose_name)
        sys.exit()

    def _login_check(self, html):
        soup = bs4.BeautifulSoup(html, PARSER)
        login = soup.find(self.check_tag, {self.check_type, self.check_text})
        if login:
            if not self.login:
                self.log.info("%s login successful" % self.verbose_name)
                self.login = True
        else:
            if self.login:
                self.login = False

            try:
                raise ParserError(self.name, "Can't login to %s. Check cookie." % self.verbose_name)
            except:
                self._crash()

def singleton(class_):
  instances = {}
  def getinstance(*args, **kwargs):
    if class_ not in instances:
        instances[class_] = class_(*args, **kwargs)
    return instances[class_]
  return getinstance

@singleton
class SteamParser(Parser):
    name = "Steam"
    verbose_name = "«Steam Community»"
    site_url = "http://steamcommunity.com/"
    check_tag = "a"
    check_type = "class"
    check_text = "user_avatar"
    cookies = {'steamLogin': None}
    cookies_file = 'Steam.cook'

    @property
    def wishlist(self):
        try:
            return self.preload_wishlist
        except AttributeError:
            self.log.info('Fetching Steam Wishlist.')
            self.preload_wishlist = []

            url = "http://steamcommunity.com/profiles/%s/wishlist/" % self.config["steamLogin"][:17]
            html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
            self._login_check(html)
            soup = bs4.BeautifulSoup(html, PARSER)
            items = soup.find_all('div', {"class", 'wishlistRow'})
            i = 0
            for item in items:
                i += 1
                try:
                    price = item.find('div', {'class': 'price'}).text.strip()
                    price_old = ''
                except AttributeError:
                    try:
                        price = item.find('div', {'class': 'discount_final_price'}).text.strip()
                        price_old = item.find('div', {'class': 'discount_original_price'}).text.strip()
                    except:
                        price = ''
                        price_old = ''

                data = {'num': i, 'id': str.strip(item['id'], 'game_'),
                        'title': item.find('h4', {'class': 'ellipsis'}).text,
                        'logo': item.a.img['src'], 'page': item.find('div', {'class': 'storepage_btn_ctn'}).a['href'],
                        'price': price, 'price_old': price_old}

                self.preload_wishlist.append(data)

            self.log.info('In You Steam Wishlist %s games.' % len(self.preload_wishlist))

            for game in self.config['wishlist'].split('; '):
                self.preload_wishlist.append({'title': game})

            return self.preload_wishlist

    @property
    def library(self):
        try:
            return self.preload_library
        except AttributeError:
            self.log.info('Fetching Steam Library.')

            url = "http://steamcommunity.com/profiles/%s/games/?tab=all" % self.config["steamLogin"][:17]
            html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
            self._login_check(html)

            for row in html.decode().splitlines():
                if 'var rgGames = ' in row:
                    self.preload_library = json.loads(str.strip(str.rstrip(str.replace(row, 'var rgGames = ', ''), ';')))

            self.log.info('In You Steam Library %s games.' % len(self.preload_library))

            return self.preload_library


class Harvester(Parser):
    required_filters = []
    disabled_filters = []
    internal_filters = []

    def __init__(self, queue, log_level):
        super(Harvester, self).__init__(queue, log_level)
        self.filters = self.required_filters
        # I know it's shit ^_^
        try:
            # list(map(lambda s: self.filters.append(s) if s not in self.filters else None,
            #          map(lambda s: s if len(s) > 1 else s[0],
            #              map(lambda s: list(map(lambda s: s.strip(), s)),
            #                  map(lambda s: s.split('='),
            #                      map(lambda s: s if s else None, self.config['filters'].split(',')))))))

            [self.filters.append(x) if x not in self.filters else None for x in
                [x if len(x) > 1 else x[0] for x in
                    [[x.strip() for x in x.split('=')] for x in
                        [x for x in self.config['filters'].split(',') if x ]]]]
        except (KeyError, AttributeError):
            pass

        self.filters = [f for f in self.filters if f not in self.disabled_filters]

        self.preload_level = None

        if 'wishlist' in self.filters:
            try:
                self.filters.remove('library')
            except:
                pass

    def start(self):
        self.log.info("Starting %s harvester..." % self.verbose_name)

        sow = self._sow()
        reap = self._reap()
        if reap:
            self.log.info('You have not accepted prizes, check it at %s !' % self.site_url)
        else:
            self.log.info("You don't win anything. For now...")
        timestamp = datetime.now()

        results = {'timestamp': timestamp, 'status': 'ok', 'sow': sow, 'reap': reap}

        self.log.info("Harvesting %s is over!" % self.verbose_name)

        self.queue.put(results)

    @property
    @abc.abstractproperty
    def level(self):
        level = None

        return level

    @property
    @abc.abstractproperty
    def points(self):
        points = None

        return points

    def _sow(self):
        giveaways_enter = []
        sow = True
        points = self.points

        page = 1
        while sow:
            giveaways = self._get_giveaways(page)
            if not giveaways:
                self.log.info('No more giveaways.')
                sow = False
                break

            for flt in self.filters:
                if flt not in self.internal_filters:
                    if type(flt) == str:
                        giveaways = list(filter(getattr(self, "_filter_%s" % flt), giveaways))
                    elif type(flt) == list:
                        giveaways = getattr(self, "_arged_filter_%s" % flt[0])(giveaways, int(flt[1]))

            page += 1

            for giveaway in giveaways:
                if points >= giveaway.points:
                    status = self._enter_giveaway(giveaway)
                    if status == 'ok':
                        points -= giveaway.points
                        giveaways_enter.append({'title': giveaway.title, 'href': giveaway.href})
                        self.log.info('Take part in «%s» giveaway.' % giveaway.title)
                else:
                    self.log.info("Not Enough Points.")
                    sow = False
                    break

        return giveaways_enter

    @abc.abstractmethod
    def _reap(self):
        return ({'title': None, 'href': None},)

    @abc.abstractmethod
    def _get_giveaways(self, page):
        pass

    @abc.abstractmethod
    def _enter_giveaway(self):
        return 'ok'

    def _arged_filter_trust(self, giveaways, trust):
        # exclude giveaways base on author's feedback
        if trust == -1:
            return giveaways
        else:
            return [g if g.trust_points >= trust else None for g in giveaways]

    def _arged_filter_max_points(self, giveaways, points):
        return [g if g.points <= points else None for g in giveaways]

    def _arged_filter_min_points(self, giveaways, points):
        return [g if g.points >= points else None for g in giveaways]

    def _arged_filter_min_level(self, giveaways, ):
        return [g if g.level >= level else None for g in giveaways]

    def _filter_trust(self, giveaway):
        # exclude giveaways base on author's feedback
        if giveaway.trust_points > 0:
            return giveaway

    def _filter_entered(self, giveaway):
        # exclude giveaways that alredy inter
        if not giveaway.entered:
            return giveaway

    def _filter_level(self, giveaway):
        # exclude giveaways that to hight level
        if not self.preload_level:
            self.preload_level = self.level

        if giveaway.level <= self.preload_level:
            return giveaway

    def _filter_library(self, giveaway):
        # exclude game's giveaways that alredy in yor lybraly
        if not giveaway.in_library:
            return giveaway

    def _filter_wishlist(self, giveaway):
        # exclude game's giveaways that what not in you wishlist
        if giveaway.in_wishlist:
            return giveaway

    def _filter_dlc(self, giveaway):
        if not giveaway.dlc:
            return giveaway


class Giveaway(Parser):
    def __init__(self, queue, log_level, href, giveaway_id=None, title=None, entered=False, level=None, points=None,
                 dlc = False, profile_url=None, trust_points=None, in_wishlist=False,):
        super(Giveaway, self).__init__(queue, log_level)
        self.giveaway_id = giveaway_id
        self.title = title
        self.href = href
        self.entered = entered
        self.level = level
        self.points = points
        self.profile_url = profile_url
        self.trust_points = trust_points

        self.steam = None
        self.wishlist = None
        self.library = None

    def _login_check(self, html):
        soup = bs4.BeautifulSoup(html, PARSER)
        login = soup.find(self.check_tag, {self.check_type, self.check_text})
        if login:
            if not self.login:
                self.login = True
        else:
            if self.login:
                self.login = False


    @property
    def in_wishlist(self):
        in_wishlist = False

        if not self.steam:
            self.steam = SteamParser(self.queue, self.log_level)

        if not self.wishlist:
            self.wishlist = self.steam.wishlist

        for game in self.wishlist:
            if re.sub('[^a-z0-9]', '', str.lower(self.title)) == re.sub('[^a-z0-9]', '', str.lower(game["title"])):
                in_wishlist = True
                break

        return in_wishlist

    @property
    def in_library(self):
        in_library = False

        if not self.steam:
            self.steam = SteamParser(self.queue, self.log_level)

        if not self.library:
            self.library = self.steam.library

        for game in self.library:
            if re.sub('[^a-z0-9]', '', str.lower(self.title)) == re.sub('[^a-z0-9]', '', str.lower(game["name"])):
                in_library = True
                break

        return in_library


class SteamGiftsHarvester(Harvester):
    name = "SteamGifts"
    verbose_name = "«Steam Gifts»"
    site_url = "https://www.steamgifts.com"
    check_tag = "div"
    check_type = "class"
    check_text = "nav__avatar-inner-wrap"
    cookies = {'PHPSESSID': None}
    required_filters = ['entered', 'level', 'library']
    disabled_filters = ['dlc']
    internal_filters = ['wishlist']

    @property
    def level(self):
        html = self.session.get(self.site_url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        level = int(re.findall('\d+', soup.find('span', {'class', 'nav__points'}).nextSibling.nextSibling.text)[0])

        return level

    @property
    def points(self):
        html = self.session.get(self.site_url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        points = int(soup.find('span', {'class', 'nav__points'}).text)

        return points

    def _get_giveaways(self, page):
        giveaways = []
        url = '%s/giveaways/search' % self.site_url
        params = {'page': page}
        try:
            if 'wishlist' in self.filters:
                params.update({'type': 'wishlist'})
        except:
            pass

        html = self.session.get(url, cookies=self.cookies, params=params,
                                headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        items = soup.find('div', {'class': 'page__heading'}).next_sibling.next_sibling.find_all('div', {
            'class': 'giveaway__row-outer-wrap'})

        for item in items:
            header = item.find('a', {'class': 'giveaway__heading__name'})
            href = "%s%s" % (self.site_url, header['href'])

            giveaway = SteamGiftsGiveaway(self.queue, self.log_level, href)

            giveaway.title = header.text.strip()

            giveaway.giveaway_id = int(item['data-game-id'])

            if item.find('div', {'class': 'is-faded'}):
                giveaway.entered = True
            else:
                giveaway.entered = False

            try:
                giveaway.level = int(re.findall('\d+', item.find('div', {'title': 'Contributor Level'}).text)[0])
            except AttributeError:
                giveaway.level = 0

            giveaway.points = int(re.findall('\d+', item.find('span', {'class': 'giveaway__heading__thin'}).text)[0])

            giveaway.profile_url = "%s%s" % (self.site_url, item.find('a', {'class': 'giveaway__username'})['href'])

            giveaways.append(giveaway)

        return giveaways

    def _enter_giveaway(self, giveaway):
        try:
            html = self.session.get(giveaway.href, cookies=self.cookies,
                                    headers={'User-Agent': self.user_agent}).content
            self._login_check(html)
            soup = bs4.BeautifulSoup(html, PARSER)

            form = soup.find('div', {'class': 'sidebar'}).find('form')
            xsrf_token = form.find('input', {'name': 'xsrf_token'})['value']
            do = 'entry_insert'
            code = form.find('input', {'name': 'code'})['value']

            data = {'xsrf_token': xsrf_token, 'do': do, 'code': code}

            url = "%s/ajax.php" % self.site_url
            code = self.session.post(url, cookies=self.cookies, data=data,
                                     headers={'User-Agent': self.user_agent}).status_code
        except:
            return 'error'

        if code == 200:
            return 'ok'
        else:
            return 'error'

    def _reap(self):
        giveaways_win = []

        url = '%s/giveaways/won' % self.site_url
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        items = soup.find('div', {'class': 'table__rows'}).find_all('div', {'class': 'table__row-outer-wrap'})

        for item in items:
            not_received = item.find('div', {'class': 'table__gift-feedback-received is-hidden'})
            if not_received:
                item_header = item.find('a', {'class': 'table__column__heading'})
                item_title = item_header.text.strip()
                item_href = "%s%s" % (self.site_url, item_header['href'])

                giveaways_win.append({'title': item_title, 'href': item_href}, )

            else:
                continue

        return giveaways_win


class SteamGiftsGiveaway(Giveaway):
    name = "SteamGifts"
    verbose_name = "«Steam Gifts»"
    site_url = "https://www.steamgifts.com"
    check_tag = "div"
    check_type = "class"
    check_text = "nav__avatar-inner-wrap"
    cookies = {'PHPSESSID': None}

    def __init__(self, queue, log_level, href, giveaway_id=None, title=None, entered=False, level=None, points=None, profile_url=None):
        super(Giveaway, self).__init__(queue, log_level)
        self.giveaway_id = giveaway_id
        self.title = title
        self.href = href
        self.entered = entered
        self.level = level
        self.points = points
        self.profile_url = profile_url

        self.steam = None
        self.wishlist = None
        self.library = None

    @property
    def trust_points(self):
        html = self.session.get(self.profile_url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        gift_sent_row = soup.find('span', {'title': re.compile('\d+ Awaiting Feedback, \d+ Not Received')})
        gift_wait, gift_fail = list(map(lambda i: int(i), re.findall('\d+', gift_sent_row['title'])))
        gift_sent = int(gift_sent_row.a.text.replace(',', ''))

        trust_points = gift_sent - gift_wait - gift_fail

        return trust_points

    @property
    def in_library(self):
        html = self.session.get(self.href, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        try:
            error = soup.find('div', {'class', 'sidebar__error'}).text.strip()
        except AttributeError:
            return False
        else:
            if error == 'Exists in Account':
                return True
            else:
                return False


# TODO incapsula bypass
class IndieGalaHarvester(Harvester):
    name = "IndieGala"
    verbose_name = "«Indie Gala»"
    site_url = "https://www.indiegala.com/giveaways"
    check_tag = "span"
    check_type = "class"
    check_text = "account-email"
    cookies = {'auth': None, 'incap_ses_586_255598': None, 'incap_ses_408_255598': None}
    required_filters = ['entered', 'level']
    disabled_filters = ['dlc']

    @property
    def level(self):
        url = "%s/get_user_level_and_coins" % self.site_url
        data = self.session.get(url, headers={'User-Agent': self.user_agent}).json()

        try:
            if data['status'] == 'ok':
                return data['current_level']
            else:
                raise ParserError(self.name, "Can't get %s level." % self.verbose_name)
        except KeyError:
            raise ParserError(self.name, "Can't get %s level." % self.verbose_name)

    @property
    def points(self):
        html = self.session.get(self.site_url, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        points = int(soup.find('span', {'id': 'silver-coins-menu'}).text)

        return points

    def _get_giveaways(self, page):
        giveaways = []
        url = '%s/%s' % (self.site_url, page)

        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        items = soup.find('div', {'class': 'tickets-row'}).find_all('div', {'class': 'tickets-col'})
        for item in items:
            header = item.find('div', {'class': 'box_pad_5'}).h2.a
            href = "%s%s" % (self.site_url, str.replace(header['href'], '/giveaways', '', 1))
            giveaway = IndieGalaGiveaway(self.queue, self.log_level, href)

            giveaway.title = header['title']

            giveaway.giveaway_id = item.find('div', {'class': 'ticket-right'}).div['rel']

            if item.find('aside', {'class': 'giv-coupon'}):
                giveaway.entered = False
            else:
                giveaway.entered = True

            giveaway.level = int(re.findall('\d+', item.find('div', {'class': 'type-level-cont'}).find('div', {'class': 'spacer-v-5'}).next.strip())[0])

            giveaway.points = int(item.find('div', {'class': 'ticket-price'}).strong.text.strip())

            creater = item.find('div', {'class': 'steamnick'}).a

            giveaway.profile_url = "%s%s" % (str.replace(self.site_url, '/giveaways', '', 1), creater['href'])

            giveaways.append(giveaway)

        return giveaways

    def _enter_giveaway(self, giveaway):
        try:
            url = '%s/new_entry' % self.site_url

            data = {'giv_id': giveaway.giveaway_id, 'ticket_price': giveaway.points}

            data = self.session.post(url, cookies=self.cookies, data=json.dumps(data),
                                     headers={'User-Agent': self.user_agent}).json()

            return data['status']
        except:
            return 'error'

    def _reap(self):
        reap = True
        url = '%s/library_completed' % self.site_url
        while reap:
            data = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
            try:
                html = json.loads(data)['html']
            except:
                break

            soup = bs4.BeautifulSoup(html, PARSER)
            items = soup.find_all('ul', {'class': 'giveaways-completed-list'})[0].find_all('li')

            try:
                for item in items:
                    if "No results." in item.text:
                        reap = False
                        break
                    else:
                        r_url = '%s/check_if_won' % self.site_url

                        entry_id = item.find('input', {'name': 'entry_id'})['value']

                        data = {'entry_id': entry_id}

                        self.session.post(r_url, cookies=self.cookies, data=json.dumps(data),
                                          headers={'User-Agent': self.user_agent})
            except TypeError:
                pass

        giveaways_win = []
        data = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        html = json.loads(data)['html']

        soup = bs4.BeautifulSoup(html, PARSER)
        items = soup.find_all('ul', {'class': 'giveaways-completed-list'})[1].find_all('li')
        try:
            for item in items:
                if item.find('button', {'class': 'btn-open-leave-feedback-form'}):
                    item_header = item.find('a', {'title': 'View giveaway details'})
                    item_title = item_header.text.strip()
                    item_href = "%s%s" % (self.site_url, item_header['href'])

                    giveaways_win.append({'title': item_title, 'href': item_href}, )

                else:
                    continue

        except TypeError:
            pass

        return giveaways_win


class IndieGalaGiveaway(Giveaway):
    name = "IndieGala"
    verbose_name = "«Indie Gala»"
    site_url = "https://www.indiegala.com/giveaways"
    check_tag = "span"
    check_type = "class"
    check_text = "account-email"
    cookies = {'auth': None, 'incap_ses_586_255598': None}

    def __init__(self, queue, log_level, href, giveaway_id=None, title=None, entered=False, level=None, points=None, profile_url=None):
        super(Giveaway, self).__init__(queue, log_level)
        self.giveaway_id = giveaway_id
        self.title = title
        self.href = href
        self.entered = entered
        self.level = level
        self.points = points
        self.profile_url = profile_url

        self.steam = None
        self.wishlist = None
        self.library = None

    @property
    def trust_points(self):
        html = self.session.get(self.profile_url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        try:
            positive = int(soup.find('span', {'title': 'Positive feedbacks'}).text)
            negative = int(soup.find('span', {'title': 'Negative feedbacks'}).text)
            points = positive + negative
        except:
            self.log.debug("Can't get feedbacks points, trust points set to -1")
            points = -1

        return points

    @property
    def in_library(self):
        html = self.session.get(self.href, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        if soup.find('div', {'class': 'on-steam-library-corner'}):
            return True
        else:
            return False


def spawner(name, queue, log_level):
    if name == "SteamGifts":
        harvester = SteamGiftsHarvester(queue, log_level)
        harvester.start()

    elif name == "IndieGala":
        harvester = IndieGalaHarvester(queue, log_level)
        harvester.start()


def main():
    # multiprocessing.set_start_method('spawn')  #set mt start method like on windows for testing
    opt_parser = OptionParser()
    opt_parser.add_option("--debug", action="store_true", dest="debug", default=False, help="Enable debug messanges")
    options, args = opt_parser.parse_args()

    log = logging.getLogger('Main')
    if not log.hasHandlers():
        formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s]: %(message)s',
                                      "%Y-%m-%d %H:%M:%S")
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        log.addHandler(console)

    if options.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    log.setLevel(log_level)

    log.info("WELCOME TO GIVEAWAY BOT REBORN!!!")

    config = configparser.ConfigParser()
    try:
        config.read_file(open("giveaway_bot.ini"))
    except FileNotFoundError:
        log.error("No config file. Please copy «giveaway_bot.exp» as «giveaway_bot.ini» and edit it.")
        sys.exit()

    config = config['main']

    if config['User_Agent']:
        global User_Agent
        User_Agent = config['User_Agent']

    while True:
        bot = GiveawayBot(log_level)
        try:
            bot.start()
            for i in range(int(config['sleepTime'])):
                processes_logs = bot.processes_logs
                for key in processes_logs:
                    queue = bot.processes_logs[key]
                    while not queue.empty():
                        results = queue.get()
                        if results['status'] == "ok":
                            if len(results['reap']) > 0:
                                log.info(
                                    '[%(timestamp)s] %(key)s Harvester end work takes part in %(num)s giveaways, and YOU WIN something!' %
                                    {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key,
                                     'num': len(results['sow'])})
                            else:
                                log.info(
                                    "[%(timestamp)s] %(key)s Harvester end work: takes part in %(num)s giveaways, and you don't win anything. For now..." %
                                    {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key,
                                     'num': len(results['sow'])})

                        elif results['status'] == "error":
                            log.error('[%(timestamp)s] %(key)s Harvester end work with error' %
                                      {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key})

                time.sleep(60)

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
            bot.stop()


if __name__ == '__main__':
    main()
