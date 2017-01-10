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
import requests
import random
from datetime import datetime, timedelta
from optparse import OptionParser
from http import cookiejar
from urllib.error import HTTPError
import urllib.parse

import bs4

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

    def __init__(self, log_level):
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

        try:
            self.user_agent = User_Agent
        except AttributeError:
            pass

        self.cookies_file = '%s.cookies' % self.name
        self.cj = cookiejar.LWPCookieJar(self.cookies_file)
        try:
            self.cj.load()
        except FileNotFoundError:
            for key in self.cookies:
                self.cookies[key] = self.config[key]

            netloc = urllib.parse.urlparse(self.site_url).netloc
            expires = datetime.now() + timedelta(days=365)
            expires = expires.timestamp()

            requests.utils.cookiejar_from_dict(self.cookies, cookiejar=self.cj, domain=netloc, expires=expires, discard=False, rest={})

        self.session = requests.Session()
        self.session.cookies = self.cj
        try:
            self.login = self._login_check()
        except ParserError:
            self._crash()

    def __del__(self):
        if self.login:
            self.cj.save()
        else:
            try:
                os.remove(self.cookies_file)
            except FileNotFoundError:
                pass

    def _crash(self):
        self.log.error('Parsing %s interrupted.' % self.verbose_name)
        sys.exit()

    def _login_check(self):
        try:
            html = self.session.get(self.site_url, headers={'User-Agent': self.user_agent}).content
        except HTTPError as e:
            self.login_error = True
            raise ParserError(self.name, "Can't login to %s, HTTPError: %s. Check cookie, or wait some time." %
                              (self.verbose_name, e.code))

        soup = bs4.BeautifulSoup(html, PARSER)
        login = soup.find(self.check_tag, {self.check_type, self.check_text})
        if login:
            self.log.info("%s login successful" % self.verbose_name)
            return True
        else:
            self.login_error = True
            raise ParserError(self.name, "Can't login to %s. Check cookie." % self.verbose_name)

class SteamParser(Parser):
    name = "Steam"
    verbose_name = "«Steam Community»"
    site_url = "http://steamcommunity.com/"
    check_tag = "a"
    check_type = "class"
    check_text = "user_avatar"
    cookies = {'steamLogin': None}

    @property
    def wishlist(self):
        self.log.info('Fetching Steam Wishlist.')
        wishlist = []

        url = "http://steamcommunity.com/profiles/%s/wishlist/" % self.config["steamLogin"][:17]
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
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

            wishlist.append(data)

        self.log.info('In Steam Wishlist %s games.' % len(wishlist))

        for game in self.config['wishlist'].split('; '):
            wishlist.append({'title': game})

        return wishlist


class Harvester(Parser):
    def __init__(self, queue, log_level):
        self.queue = queue
        super(Harvester, self).__init__(log_level)

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

    def _crash(self):
        timestamp = datetime.now()
        results = {'timestamp': timestamp, 'status': 'error'}
        self.queue.put(results)

        self.log.error('Harvesting %s interrupted.' % self.verbose_name)
        sys.exit()

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

    @abc.abstractmethod
    def _sow(self):
        giveaways_inter = ({'title': None, 'href': None},)
        giveaways_inter = ()

        return giveaways_inter

    @abc.abstractmethod
    def _reap(self):
        giveaways_win = ({'title': None, 'href': None},)
        giveaways_win = ()

        return giveaways_win

    @abc.abstractmethod
    def _giveaway_entry(self):
        result = None

        return result

class ExternalWishlistHarvester(Harvester):
    def __init__(self, queue, log_level):
        super(ExternalWishlistHarvester, self).__init__(queue, log_level)
        if int(self.config['wishlist']):
            self.wishlist = SteamParser(log_level).wishlist
        else:
            self.wishlist = None

    def _in_wishlist(self, title):
        in_wishlist = False
        for wish in self.wishlist:
            if re.escape(str.lower(title)) == re.escape(str.lower(wish["title"])):
                in_wishlist = True
                break

        return in_wishlist

class SteamGiftsHarvester(Harvester):
    name = "SteamGifts"
    verbose_name = "«Steam Gifts»"
    site_url = "https://www.steamgifts.com"
    check_tag = "div"
    check_type = "class"
    check_text = "nav__avatar-inner-wrap"
    cookies = {'PHPSESSID':None}

    @property
    def level(self):
        html = self.session.get(self.site_url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        soup = bs4.BeautifulSoup(html, PARSER)
        level = int(re.findall('\d', soup.find('span', {'class', 'nav__points'}).nextSibling.nextSibling.text)[0])

        return level

    @property
    def points(self):
        html = self.session.get(self.site_url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        soup = bs4.BeautifulSoup(html, PARSER)
        points = int(soup.find('span', {'class', 'nav__points'}).text)

        return points

    def _sow(self):
        giveaways_inter = []
        params = {}
        sow = True

        url = '%s/giveaways/search' % self.site_url
        if int(self.config['wishlist']):
            params.update({'type': 'wishlist'})

        i = 1
        while sow:
            html = self.session.get(self.site_url, cookies=self.cookies, params=params, headers={'User-Agent': self.user_agent}).content
            soup = bs4.BeautifulSoup(html, PARSER)

            items = soup.find('div', {'class': 'page__heading'}).next_sibling.next_sibling.find_all('div', {
                'class': 'giveaway__row-outer-wrap'})
            for item in items:
                if item.find('div', {'class': 'is-faded'}):
                    continue
                else:
                    item_header = item.find('a', {'class': 'giveaway__heading__name'})
                    item_title = item_header.text.strip()
                    item_href = "%s%s" % (self.site_url, item_header['href'])

                    html = self.session.get(item_href, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
                    page = bs4.BeautifulSoup(html, PARSER)
                    try:
                        btn_text = page.find('div', {'class': 'sidebar__entry-insert'}).text
                    except:
                        btn_text = page.find('div', {'class': 'sidebar__error'}).text.strip()
                        if btn_text == 'Not Enough Points':
                            self.log.info("%s." % btn_text)
                            sow = False
                            break
                        else:
                            self.log.debug("Can't inter in giveaway.%s" % btn_text)
                            continue
                    else:
                        status = self._giveaway_entry(page)
                        if status == 200:
                            giveaways_inter.append({'title': item_title, 'href': item_href}, )
                            self.log.info('Take part in «%s» giveaway.' % item_title)

            if sow:
                page = soup.find('div', {'class': 'pagination__navigation'}).find_all('a')[-1]
                if page.span.text == 'Next':
                    i += 1
                    params.update({'page': i})
                else:
                    sow = False
                    self.log.info('No more giveaways.')

        return giveaways_inter

    def _reap(self):
        giveaways_win = []

        url = '%s/giveaways/won' % self.site_url
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
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

    def _giveaway_entry(self, page):
        url = "%s/ajax.php" % self.site_url

        form = page.find('div', {'class': 'sidebar'}).find('form')
        xsrf_token = form.find('input', {'name': 'xsrf_token'})['value']
        do = 'entry_insert'
        code = form.find('input', {'name': 'code'})['value']

        data = {'xsrf_token': xsrf_token, 'do': do, 'code': code}

        html = self.session.post(url, cookies=self.cookies, data=data, headers={'User-Agent': self.user_agent}).content

        if html:
            status = 200

        return status

#TODO incapsula bypass
class IndieGalaHarvester(ExternalWishlistHarvester):
    name = "IndieGala"
    verbose_name = "«Indie Gala»"
    site_url = "https://www.indiegala.com/giveaways"
    check_tag = "span"
    check_type = "class"
    check_text = "account-email"
    cookies = {'auth':None, 'incap_ses_586_255598': None}

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
        soup = bs4.BeautifulSoup(html, PARSER)

        points = int(soup.find('span', {'id': 'silver-coins-menu'}).text)

        return points

    def _sow(self):
        level = self.level
        points = self.points
        giveaways_inter = []
        sow = True

        url = self.site_url
        if self.config['sort'] and self.config['direction']:
            params = '%s/%s' % (self.config['sort'], self.config['direction'])
        elif self.config['sort']:
            params = '%s/asc' % self.config['sort']
        elif self.config['direction']:
            params = 'expiry/%s' % self.config['direction']
        else:
            params = 'expiry/asc'

        i = 1
        while sow:
            self.log.debug('Starting parse page %s' % i)
            r_url = "%s/%s/%s" % (url, i, params)
            html = self.session.get(r_url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
            soup = bs4.BeautifulSoup(html, PARSER)

            items = soup.find('div', {'class': 'tickets-row'}).find_all('div', {'class': 'tickets-col'})
            for item in items:
                item_level = int(re.findall(r'\d', item.find('div', {'class': 'type-level-cont'}).find('div', {
                    'class': 'spacer-v-5'}).next.strip())[0])
                coupon = item.find('aside', {'class': 'giv-coupon'})
                item_header = item.find('div', {'class': 'box_pad_5'}).h2.a
                item_title = item_header['title']
                item_url = "%s%s" % (self.site_url, str.replace(item_header['href'], '/giveaways', '', 1))
                item_creater = item.find('div', {'class': 'steamnick'}).a
                item_creater_url = "%s%s" % (str.replace(self.site_url, '/giveaways', '', 1), item_creater['href'])
                trust_points = self._get_trust_points(item_creater_url)
                giv_id = item.find('div', {'class': 'ticket-right'}).div['rel']
                ticket_price = int(item.find('div', {'class': 'ticket-price'}).strong.text.strip())

                if level < item_level or not coupon or trust_points < int(self.config['trust_points']):
                    continue
                elif not int(self.config['wishlist']):
                    if not int(self.config['in_steam']):
                        in_steam = self._in_steam(item_url)
                        if not in_steam:
                            if points < ticket_price:
                                sow = False
                                self.log.info("Not Enough Coins.")
                                break
                            else:
                                resp = self._giveaway_entry(giv_id, ticket_price)
                                status = resp['status']
                                points = resp['new_amount']
                                if status == 'ok':
                                    giveaways_inter.append({'title': item_title, 'href': item_url}, )
                                    self.log.info('Take part in «%s» giveaway.' % item_title)
                        else:
                            self.log.debug('You alrady own «%s»' % item_title)
                            continue

                    else:
                        if points < ticket_price:
                            sow = False
                            self.log.info("Not Enough Coins.")
                            break
                        else:
                            resp = self._giveaway_entry(giv_id, ticket_price)
                            status = resp['status']
                            points = resp['new_amount']
                            if status == 'ok':
                                giveaways_inter.append({'title': item_title, 'href': item_url}, )
                                self.log.info('Take part in «%s» giveaway.' % item_title)

                else:
                    in_wishlist = self._in_wishlist(item_title)
                    if in_wishlist:
                        if points < ticket_price:
                            sow = False
                            self.log.info("Not Enough Coins.")
                            break
                        else:
                            resp = self._giveaway_entry(giv_id, ticket_price)
                            status = resp['status']
                            points = resp['new_amount']
                            if status == 'ok':
                                giveaways_inter.append({'title': item_title, 'href': item_url}, )
                                self.log.info('Take part in «%s» giveaway.' % item_title)

            if sow:
                try:
                    page = soup.find('div', {'class': 'page-nav'}).find_all('div', {'class': 'page-link-cont'})[-2].a
                    i += 1
                except AttributeError:
                    sow = False
                    self.log.info('No more giveaways.')

        return giveaways_inter

    def _reap(self):
        giveaways_win = []

        url = '%s/library_completed' % self.site_url

        data = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        html = json.loads(data)['html']
        soup = bs4.BeautifulSoup(html, PARSER)
        items = soup.find_all('ul', {'class': 'giveaways-completed-list'})[0].find_all('li')
        try:
            for item in items:
                r_url = '%s/check_if_won' % self.site_url

                entry_id = item.find('input', {'name': 'entry_id'})['value']

                data = {'entry_id': entry_id}

                self.session.post(r_url, cookies=self.cookies, data=json.dumps(data), headers={'User-Agent': self.user_agent})
        except TypeError:
            pass

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

    def _giveaway_entry(self, giv_id, ticket_price):
        url = '%s/new_entry' % self.site_url

        data = {'giv_id': giv_id, 'ticket_price': ticket_price}

        data = self.session.post(url, cookies=self.cookies, data=json.dumps(data), headers={'User-Agent': self.user_agent}).json()

        return data

    def _in_steam(self, url):
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        soup = bs4.BeautifulSoup(html, PARSER)

        if soup.find('div', {'class': 'on-steam-library-corner'}):
            return True
        else:
            return False

    def _get_trust_points(self, url):
        html = self.session.get(url, cookies=self.cookies, headers={'User-Agent': self.user_agent}).content
        soup = bs4.BeautifulSoup(html, PARSER)
        try:
            positive = int(soup.find('span', {'title': 'Positive feedbacks'}).text)
            negative = int(soup.find('span', {'title': 'Negative feedbacks'}).text)
            points = positive + negative
        except:
            self.log.debug("Can't get feedbacks points, trust points set to -1")
            points = -1

        return points

def spawner(name, queue, log_level):
    if name == "SteamGifts":
        harvester = SteamGiftsHarvester(queue, log_level)
        harvester.start()

    elif name == "IndieGala":
        harvester = IndieGalaHarvester(queue, log_level)
        harvester.start()

def main():
    #multiprocessing.set_start_method('spawn')  #set mt start method like on windows for testing
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
                                    '[%(timestamp)s] %(key)s Harvester end work takes part in %(num)s giveaways, and you have win something.' %
                                    {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key,
                                     'num': len(results['reap'])})
                            else:
                                log.info(
                                    "[%(timestamp)s] %(key)s Harvester end work: takes part in %(num)s giveaways, and you don't win anything. For now..." %
                                    {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key,
                                     'num': len(results['reap'])})

                        elif results['status'] == "error":
                            log.error('[%(timestamp)s] %(key)s Harvester end work with error' %
                                     {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key})

                time.sleep(60)

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
            bot.stop()

if __name__ == '__main__':
    main()