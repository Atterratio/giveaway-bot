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
from datetime import datetime
from optparse import OptionParser

import bs4
import requests

try:
    import lxml
except ImportError:
    PARSER = "html.parser"
else:
    PARSER = "lxml"

os.chdir(os.path.dirname(__file__))

USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:50) Gecko/20100101 Firefox/50.0'


def caching_property(prop):
    def wrapped(self):
        name = prop.__name__
        try:
            return getattr(self, 'cached_%s' % name)

        except AttributeError:
            setattr(self, 'cached_%s' % name, prop(self))

            return getattr(self, 'cached_%s' % name)

    return wrapped


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
        """
        Base parser class
        :param queue: queue for send result or error messages to main process.
        """
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

        for key in self.cookies:
            self.cookies[key] = self.config[key]

        self.cj = requests.utils.cookiejar_from_dict(self.cookies)

        self.session = requests.Session()
        self.session.cookies = self.cj


    def _crash(self, msg):
        """
        Call if something wrong and add error to message queue
        :param msg: message to log
        """
        timestamp = datetime.now()
        results = {'timestamp': timestamp, 'status': 'error', 'msg': msg}
        self.queue.put(results)

        self.log.error(msg)
        sys.exit()


    def _login_check(self, html):
        """
        Check what loged before parse.
        :param html: content if parsing page
        """
        soup = bs4.BeautifulSoup(html, PARSER)
        login = soup.find(self.check_tag, {self.check_type, self.check_text})
        if login:
            self.log.debug("%s login successful" % self.verbose_name)
        else:
            self._crash(msg="Can't login to %s. Check cookie." % self.verbose_name)


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

    @property
    @caching_property
    def wishlist(self):
        """
        :return: steam wishlist with apend user wishlist from config
        """
        self.log.info('Fetching Steam Wishlist.')

        wishlist = []

        url = "http://steamcommunity.com/profiles/%s/wishlist/" % self.config["steamLogin"][:17]
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        items = soup.find_all('div', {"class", 'wishlistRow'})
        for item in items:
            try:
                price = item.find('div', {'class': 'price'}).text.strip()
                price_old = ''
            except AttributeError:
                try:
                    price = item.find('div', {'class': 'discount_final_price'}).text.strip()
                    price_old = item.find('div', {'class': 'discount_original_price'}).text.strip()
                except AttributeError:
                    price = ''
                    price_old = ''

            data = {'id': int(str.strip(item['id'], 'game_')),
                    'title': item.find('h4', {'class': 'ellipsis'}).text,
                    'price': price, 'price_old': price_old}

            wishlist.append(data)

        self.log.info('In You Steam Wishlist %s games.' % len(wishlist))

        local_wishlist = [int(x.strip()) for x in self.config['wishlist'].split(',') if x]

        for game_id in local_wishlist:
            data = {'id': game_id, 'title': self.get_title(game_id)}
            wishlist.append(data)

        return wishlist

    @property
    @caching_property
    def library(self):
        """
        :return: games in steam library
        """
        self.log.info('Fetching Steam Library.')

        library = []

        url = "%s/profiles/%s/games/?tab=all" % (self.site_url, self.config["steamLogin"][:17])
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)

        for row in html.decode().splitlines():
            if 'var rgGames = ' in row:
                library = json.loads(str.strip(str.rstrip(str.replace(row, 'var rgGames = ', ''), ';')))

        self.log.info('In You Steam Library %s games.' % len(library))

        return library

    def get_os_list(self, game_id):
        """
        Return list of game supported OS
        :param game_id: steam game id
        :return: ['win', 'lin', 'mac']
        """
        os_list = []
        url = "http://store.steampowered.com/app/%s" % game_id

        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        if soup.find('span', {'class': 'platform_img win'}):
            os_list.append('win')

        if soup.find('span', {'class': 'platform_img linux'}):
            os_list.append('lin')

        if soup.find('span', {'class': 'platform_img mac'}):
            os_list.append('mac')

        return os_list

    def get_type(self, game_id):
        # TODO add other types like film
        """
        Return app type
        :param game_id: steam game id
        :return: now can return only 'dlc' and 'game'
        """
        url = "http://store.steampowered.com/app/%s" % game_id

        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        if soup.find('div', {'class': 'game_area_dlc_bubble'}):
            return 'dlc'
        else:
            return 'game'

    def get_cards(self, game_id):
        """
        Return cards support status
        :param game_id:
        :return: True or False
        """
        cards = False

        url = "http://store.steampowered.com/app/%s" % game_id

        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        categories = soup.find('div', {'id': 'category_block'})
        for img in categories.find_all('img', {'class': 'category_icon'}):
            if 'ico_cards.png' in img['src']:
                cards = True
                break

        return cards

    def get_title(self, game_id):
        url = "http://store.steampowered.com/app/%s" % game_id

        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        title = soup.find('div', {'class': 'apphub_AppName'}).text

        return title


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

            [self.filters.append(x) for x in
                [x if len(x) > 1 else x[0] for x in
                    [[x.strip() for x in x.split('=')] for x in
                        [x for x in self.config['filters'].split(',') if x]]] if x not in self.filters]
        except (KeyError, AttributeError):
            pass

        self.filters = [f for f in self.filters if f not in self.disabled_filters]

        if 'wishlist' in self.filters:
            try:
                self.filters.remove('library')
            except ValueError:
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
        pass

    @property
    @abc.abstractproperty
    def points(self):
        pass

    def _sow(self):
        giveaways_enter = []
        sow = True
        points = self.points

        page = 1
        while sow:
            giveaways = self._get_giveaways(page)
            if not giveaways:
                self.log.info('No more giveaways.')
                break

            for flt in self.filters:
                if flt not in self.internal_filters:
                    try:
                        if isinstance(flt, str):
                            giveaways = getattr(self, "_filter_%s" % flt)(giveaways)
                        elif isinstance(flt, list):
                            giveaways = getattr(self, "_arged_filter_%s" % flt[0])(giveaways, flt[1])
                    except AttributeError:
                        continue

            page += 1

            for giveaway in giveaways:
                if int(points) >= int(giveaway.points):
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
        pass

    @abc.abstractmethod
    def _get_giveaways(self, page):
        pass

    def _enter_giveaway(self, giveaway):
        status = giveaway.enter()
        return status

    def _filter_trust(self, giveaways):
        """
        Exclude giveaways base on author's feedback
        :param giveaway:
        :return: equal  trust=1
        """
        return [g for g in giveaways if int(g.trust_points) > 0]

    def _arged_filter_trust(self, giveaways, trust):
        """
        Exclude giveaways base on author's feedback
        :param giveaways: list of giveaways
        :param trust: 1|0|-1
        :return: 1 - list of giveaways with positive feedback, 0 - positive and zero(balansed), -1 - not filtered
        """
        if int(trust) <= -1:
            return giveaways
        else:
            return [g for g in giveaways if int(g.trust_points) >= int(trust)]

    def _arged_filter_max_points(self, giveaways, points):
        """
        Exclude giveaways coast more then points
        :param giveaways: list of giveaways
        :return: fitered giveaways
        """
        return [g for g in giveaways if int(g.points) <= int(points)]

    def _arged_filter_min_points(self, giveaways, points):
        """
        Exclude giveaways coast less then points
        :param giveaways: list of giveaways
        :return: fitered giveaways
        """
        return [g for g in giveaways if int(g.points) >= int(points)]

    def _filter_level(self, giveaways):
        """
        Exclude giveaways that to height level
        """
        return [g for g in giveaways if int(g.level) <= self.level]

    def _arged_filter_min_level(self, giveaways, level):
        """
        Exclude giveaways with lesser level
        :param giveaways: list of giveaways
        :return: fitered giveaways
        """
        return [g for g in giveaways if int(g.level) >= int(level)]

    def _arged_filter_os(self, giveaways, os):
        """
        Exclude giveaways what not support os
        :param giveaways: list of giveaways
        :param os: target os
        :return: fitered giveaways
        """
        if os == 'all':
            return giveaways
        else:
            return [g for g in giveaways if os in g.os_list]

    def _filter_entered(self, giveaways):
        """
        Exclude giveaways that already entered
        """
        return [g for g in giveaways if not g.entered]

    def _filter_library(self, giveaways):
        """
        Exclude game's giveaways that already in yor library
        """
        return [g for g in giveaways if not g.in_library]

    def _filter_wishlist(self, giveaways):
        """
        Exclude giveaways of games that what not in you wishlist

        """
        return [g for g in giveaways if g.in_wishlist]

    def _filter_dlc(self, giveaways):
        """
        Exclude dlc's giveaways
        """
        return [g for g in giveaways if not g.dlc]

    def _filter_cards(self, giveaways):
        """
        Exclude giveaways games without cards
        """
        return [g for g in giveaways if g.cards]


class Giveaway(Parser):
    def __init__(self, queue, log_level, game_id):
        super(Giveaway, self).__init__(queue, log_level)
        self.game_id = game_id

        self.steam = None
        self.wishlist = None
        self.library = None

    @property
    @caching_property
    def in_wishlist(self):
        in_wishlist = False

        if self.steam is None:
            self.steam = SteamParser(self.queue, self.log_level)

        if self.wishlist is None:
            self.wishlist = self.steam.wishlist

        for game in self.wishlist:
            if self.game_id == game["id"]:
                in_wishlist = True
                break

        return in_wishlist

    @property
    @caching_property
    def in_library(self):
        in_library = False

        if self.steam is None:
            self.steam = SteamParser(self.queue, self.log_level)

        if self.library is None:
            self.library = self.steam.library

        for game in self.library:
            if self.game_id == game["appid"]:
                in_library = True
                break

        return in_library

    @property
    @caching_property
    def os_list(self):
        if not self.steam:
            self.steam = SteamParser(self.queue, self.log_level)

        return self.steam.get_os_list(self.game_id)

    @property
    @caching_property
    def dlc(self):
        if not self.steam:
            self.steam = SteamParser(self.queue, self.log_level)

        app_type = self.steam.get_type(self.game_id)

        if app_type == 'dlc':
            return True
        else:
            return False

    @property
    @caching_property
    def cards(self):
        if not self.steam:
            self.steam = SteamParser(self.queue, self.log_level)

        return self.steam.get_cards(self.game_id)

    @abc.abstractmethod
    def enter(self):
        pass


class SteamGiftsHarvester(Harvester):
    name = "SteamGifts"
    verbose_name = "«Steam Gifts»"
    site_url = "https://www.steamgifts.com"
    check_tag = "div"
    check_type = "class"
    check_text = "nav__avatar-inner-wrap"
    cookies = {'PHPSESSID': None}
    required_filters = ['entered', 'level', 'library']
    internal_filters = ['library', 'level', 'os', 'wishlist']

    @property
    @caching_property
    def level(self):
        html = self.session.get(self.site_url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        level = int(re.findall('\d+', soup.find('span', {'class', 'nav__points'}).nextSibling.nextSibling.text)[0])

        return level

    @property
    @caching_property
    def points(self):
        html = self.session.get(self.site_url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        points = int(soup.find('span', {'class', 'nav__points'}).text)

        return points

    @property
    @caching_property
    def xsrf_token(self):
        html = self.session.get(self.site_url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        xsrf_token = soup.find('input', {'name': 'xsrf_token'})['value']

        return xsrf_token

    def _get_giveaways(self, page):
        self._internal_filters()

        giveaways = []
        url = '%s/giveaways/search' % self.site_url
        params = {'page': page}
        if 'wishlist' in self.filters:
            params.update({'type': 'wishlist'})

        html = self.session.get(url, cookies=self.cookies, params=params,
                                headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        items = soup.find('div', {'class': 'page__heading'}).next_sibling.next_sibling.find_all('div', {
            'class': 'giveaway__row-outer-wrap'})

        for item in items:
            header = item.find('a', {'class': 'giveaway__heading__name'})
            href = "%s%s" % (self.site_url, header['href'])

            title = header.text.strip()

            code = str.split(header['href'], '/')[2]

            if item.find('div', {'class': 'is-faded'}):
                entered = True
            else:
                entered = False

            try:
                level = int(re.findall('\d+', item.find('div', {'title': 'Contributor Level'}).text)[0])
            except AttributeError:
                level = 0

            points = int(re.findall('\d+', item.find('span', {'class': 'giveaway__heading__thin'}).text)[0])

            game_id = int(str.split(item.find('h2', {'class': 'giveaway__heading'}).find('a', {'class': 'giveaway__icon', 'target': '_blank'})['href'], '/')[4])

            profile_url = "%s%s" % (self.site_url, item.find('a', {'class': 'giveaway__username'})['href'])

            giveaway = SteamGiftsGiveaway(self.queue, self.log_level, game_id, self.xsrf_token, code, title, href, entered, level, points, profile_url)

            giveaways.append(giveaway)

        return giveaways

    def _reap(self):
        giveaways_win = []

        url = '%s/giveaways/won' % self.site_url
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
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

    def _internal_filters(self):
        if ['os', 'win'] in self.filters:
            filter_os = 1
        elif ['os', 'lin'] in self.filters:
            filter_os = 2
        elif ['os', 'mac'] in self.filters:
            filter_os = 3
        else:
            filter_os = 0

        filter_giveaways_exist_in_account = 1
        filter_giveaways_level = 1
        filter_giveaways_missing_base_game = 1

        data = {'xsrf_token': self.xsrf_token, 'filter_os': filter_os,
                'filter_giveaways_exist_in_account': filter_giveaways_exist_in_account,
                'filter_giveaways_level': filter_giveaways_level,
                'filter_giveaways_missing_base_game': filter_giveaways_missing_base_game}

        url = "%s/account/settings/giveaways" % self.site_url
        code = self.session.post(url, cookies=self.cookies, data=data,
                                 headers={'User-Agent': USER_AGENT}).status_code


class SteamGiftsGiveaway(Giveaway):
    name = "SteamGifts"
    verbose_name = "«Steam Gifts»"
    site_url = "https://www.steamgifts.com"
    check_tag = "div"
    check_type = "class"
    check_text = "nav__avatar-inner-wrap"
    cookies = {'PHPSESSID': None}

    def __init__(self, queue, log_level, game_id,  xsrf_token, code, title, href, entered, level, points, profile_url):
        super(SteamGiftsGiveaway, self).__init__(queue, log_level, game_id)
        self.xsrf_token = xsrf_token
        self.code = code
        self.title = title
        self.href = href
        self.entered = entered
        self.level = level
        self.points = points
        self.profile_url = profile_url

    @property
    @caching_property
    def trust_points(self):
        html = self.session.get(self.profile_url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        gift_sent_row = soup.find('span', {'title': re.compile('\d+ Awaiting Feedback, \d+ Not Received')})
        gift_wait, gift_fail = list(map(lambda i: int(i), re.findall('\d+', gift_sent_row['title'])))
        gift_sent = int(gift_sent_row.a.text.replace(',', ''))

        trust_points = gift_sent - gift_wait - gift_fail

        return trust_points

    def enter(self):
        data = {'xsrf_token': self.xsrf_token, 'do': 'entry_insert', 'code': self.code}

        url = "%s/ajax.php" % self.site_url
        code = self.session.post(url, cookies=self.cookies, data=data,
                                 headers={'User-Agent': USER_AGENT}).status_code

        if code == 200:
            return 'ok'
        else:
            return 'error'


# TODO incapsula bypass
class IndieGalaHarvester(Harvester):
    name = "IndieGala"
    verbose_name = "«Indie Gala»"
    site_url = "https://www.indiegala.com/giveaways"
    check_tag = "span"
    check_type = "class"
    check_text = "account-email"
    cookies = {'auth': None, 'incap_ses_586_255598': None, 'incap_ses_408_255598': None, 'incap_ses_583_255598': None}
    required_filters = ['entered', 'level']

    @property
    @caching_property
    def level(self):
        url = "%s/get_user_level_and_coins" % self.site_url
        data = self.session.get(url, headers={'User-Agent': USER_AGENT}).json()

        if data['status'] == 'ok':
            return data['current_level']
        else:
            self._crash()

    @property
    @caching_property
    def points(self):
        html = self.session.get(self.site_url, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        points = int(soup.find('span', {'id': 'silver-coins-menu'}).text)

        return points

    def _get_giveaways(self, page):
        giveaways = []
        url = '%s/%s' % (self.site_url, page)

        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        items = soup.find('div', {'class': 'tickets-row'}).find_all('div', {'class': 'tickets-col'})
        for item in items:
            header = item.find('div', {'class': 'box_pad_5'}).h2.a
            href = "%s%s" % (self.site_url, str.replace(header['href'], '/giveaways', '', 1))
            title = header['title']

            giveaway_id = item.find('div', {'class': 'ticket-right'}).div['rel']

            if item.find('aside', {'class': 'giv-coupon'}):
                entered = False
            else:
                entered = True

            level = int(re.findall('\d+', item.find('div', {'class': 'type-level-cont'}).
                                            find('div', {'class': 'spacer-v-5'}).next.strip())[0])

            points = int(item.find('div', {'class': 'ticket-price'}).strong.text.strip())

            creater = item.find('div', {'class': 'steamnick'}).a

            profile_url = "%s%s" % (str.replace(self.site_url, '/giveaways', '', 1), creater['href'])

            giveaway = IndieGalaGiveaway(self.queue, self.log_level, giveaway_id, title, href, entered, level, points, profile_url)

            if 'not guaranteed' not in item.find('div', {'class': 'type-level-cont'}).text:
                giveaway.preload_trust_points = 100

            giveaways.append(giveaway)

        return giveaways

    def _reap(self):
        reap = True
        url = '%s/library_completed' % self.site_url
        while reap:
            data = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
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
                                          headers={'User-Agent': USER_AGENT})
            except TypeError:
                pass

        giveaways_win = []
        data = self.session.get(url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
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
    cookies = {'auth': None, 'incap_ses_586_255598': None, 'incap_ses_408_255598': None, 'incap_ses_583_255598': None}

    def __init__(self, queue, log_level, giveaway_id, title, href, entered, level, points, profile_url):
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
    @caching_property
    def trust_points(self):
        html = self.session.get(self.profile_url, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        try:
            positive = int(soup.find('span', {'title': 'Positive feedbacks'}).text)
            negative = int(soup.find('span', {'title': 'Negative feedbacks'}).text)
            trust_points = positive + negative
        except AttributeError:
            self.log.debug("Can't get feedbacks points, trust points set to -1")
            trust_points = -1

        return trust_points

    @property
    @caching_property
    def in_library(self):
        html = self.session.get(self.href, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)

        if soup.find('div', {'class': 'on-steam-library-corner'}):
            return True
        else:
            return False

    @property
    @caching_property
    def game_id(self):
        html = self.session.get(self.href, cookies=self.cookies, headers={'User-Agent': USER_AGENT}).content
        self._login_check(html)
        soup = bs4.BeautifulSoup(html, PARSER)
        game_id = int(str.split(soup.find('a', {'class': 'steam-link'})['href'], '/')[4])

        return game_id

    def enter(self):
        url = '%s/new_entry' % self.site_url

        data = {'giv_id': self.giveaway_id, 'ticket_price': self.points}

        data = self.session.post(url, cookies=self.cookies, data=json.dumps(data),
                                 headers={'User-Agent': USER_AGENT}).json()

        return data['status']


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

    if config['USER_AGENT']:
        global USER_AGENT
        USER_AGENT = config['USER_AGENT']

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
