#!/usr/bin/env python3

import os
import sys
import logging
import configparser
import time
import multiprocessing
import json
import re

import bs4
import browser_cookie3

from datetime import datetime
from optparse import OptionParser
from urllib import request, parse, error

try:
    import lxml
except:
    PARSER = "html.parser"
else:
    PARSER = "lxml"

os.chdir(os.path.dirname(__file__))

#TODO: USER_AGENT from config
USER_AGENT = 'Mozilla/5.0'


class Error(Exception):
    def __init__(self, name, message):
        log = logging.getLogger(name)
        if not log.hasHandlers():
            formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s][%(processName)s]: %(message)s', "%Y-%m-%d %H:%M:%S")
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
            formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s][%(processName)s]: %(message)s', "%Y-%m-%d %H:%M:%S")
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

        self.parsers = [{"name": "Steam"}, {"name": "SteamGifts"}, {"name": "IndieGala"}]

        self.wishlist = None
        self.processes_logs = {}

    def start(self):
        for parser in self.parsers:
            if parser['name'] == "Steam":
                prs = SteamParser(self.log_level)
                self.wishlist = prs.start()
            else:
                enable = int(self.config[parser['name']]['enable'])
                if enable:
                    queue = multiprocessing.Queue()
                    self.processes_logs.update({parser['name']: queue})
                    process = multiprocessing.Process(target=spawner, args=(parser['name'], queue, self.wishlist, self.log_level), name=parser['name'])
                    process.start()
                else:
                    continue

    def stop(self):
        for child in multiprocessing.active_children():
            child.terminate()

        sys.exit()


class Parser:
    name = None
    verbose_name = None
    site_url = None
    check_tag = None
    check_type = None
    check_text = None
    cookies = {}

    def __init__(self, log_level):
        self.log = logging.getLogger(self.name)
        if not self.log.hasHandlers():
            formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s][%(processName)s]: %(message)s', "%Y-%m-%d %H:%M:%S")
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            self.log.addHandler(console)
        self.log.setLevel(log_level)

        config = configparser.ConfigParser()
        config.read_file(open("giveaway_bot.ini"))
        self.config = config[self.name]

        cookies_str = ''
        for key in self.cookies:
            cookies_str += '%s=%s;' % (key, self.config[key])

        self.cookies = cookies_str

    def start(self):
        self.log.info("Starting %s parser" % self.verbose_name)
        self._login_check()
        results = self._main()
        self.log.info("End of work %s parser" % self.verbose_name)

        return results

    def _main(self):
        pass

    def _login_check(self):
        r = request.Request(self.site_url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        html = request.urlopen(r).read().decode('utf-8')
        soup = bs4.BeautifulSoup(html, PARSER)
        login = soup.find(self.check_tag, {self.check_type, self.check_text})
        if login:
            self.log.info("%s login successful" % self.verbose_name)
        else:
            raise ParserError(self.name, "Can't login to %s. Check cookie." % self.verbose_name)


class SteamParser(Parser):
    name = "Steam"
    verbose_name = "«Steam Community»"
    site_url = "http://steamcommunity.com/"
    check_tag = "a"
    check_type = "class"
    check_text = "user_avatar"
    cookies = {'sessionid': None, 'steamLogin': None}

    def _main(self):
        list = []

        url = "http://steamcommunity.com/profiles/%s/wishlist/" % self.config["steamLogin"][:17]
        r = request.Request(url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        html = request.urlopen(r).read().decode('utf-8')
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

            data = {'num': i, 'id': str.strip(item['id'], 'game_'), 'title': item.find('h4', {'class': 'ellipsis'}).text,
                    'logo': item.a.img['src'], 'page': item.find('div', {'class': 'storepage_btn_ctn'}).a['href'],
                    'price': price, 'price_old': price_old}

            list.append(data)

        self.log.info('In Steam Wishlist %s games' % len(list))

        for game in self.config['wishlist'].split('; '):
            list.append({'title': game})

        return list


class Harvester(Parser):

    def __init__(self, wishlist, log_level):
        super(Harvester, self).__init__(log_level)

        self.wishlist = wishlist

    def start(self):
        self.log.info("Starting %s harvester" % self.verbose_name)
        self._login_check()
        results = self._main()
        self.log.info("End of work  %s harvester" % self.verbose_name)

        return results

    def _stop(self):
        self.log.warning("Interrupt of work  %s harvester" % self.verbose_name)
        for child in multiprocessing.active_children():
            child.terminate()

        sys.exit()


    def _main(self):
        self.log.debug("Startind %s sow" % self.verbose_name)
        sow = self._sow()
        self.log.debug("Stoping %s sow" % self.verbose_name)

        self.log.debug("Startind %s reap" % self.verbose_name)
        reap = self._reap()
        if reap:
            self.log.info('You win something, check it at %s !' % self.site_url)
        else:
            self.log.info("You don't win anything. For now...")

        self.log.debug("Stoping %s reap" % self.verbose_name)

        timestamp = datetime.now()

        results = {'timestamp': timestamp, 'sow': sow, 'reap': reap}

        return results

    def _sow(self):
        giveaways_inter = ({'title': None, 'href': None},)
        giveaways_inter = ()

        return giveaways_inter

    def _reap(self):
        giveaways_win = ({'title': None, 'href': None},)
        giveaways_win = ()

        return giveaways_win

    def _giveaway_entry(self):
        result = None

        return result


class SteamGiftsHarvester(Harvester):
    name = "SteamGifts"
    verbose_name = "«Steam Gifts»"
    site_url = "https://www.steamgifts.com"
    check_tag = "div"
    check_type = "class"
    check_text = "nav__avatar-inner-wrap"
    cookies = {'PHPSESSID': None}

    def _sow(self):
        giveaways_inter = []
        params = {}
        sow = True

        if int(self.config['wishlist']):
            url = '%s/giveaways/search' % self.site_url
            params.update({'type': 'wishlist'})
        else:
            url = self.site_url

        i = 1
        while sow:
            self.log.debug('Starting parse page %s' % i)
            r_url = "%s?" % url
            for key in params:
                r_url = '%s%s=%s&' % (r_url, key, params[key])

            r = request.Request(r_url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
            html = request.urlopen(r).read().decode('utf-8')
            soup = bs4.BeautifulSoup(html, PARSER)

            items = soup.find('div', {'class': 'page__heading'}).next_sibling.next_sibling.find_all('div', {'class': 'giveaway__row-outer-wrap'})
            for item in items:
                if item.find('div', {'class': 'is-faded'}):
                    continue
                else:
                    item_header = item.find('a', {'class': 'giveaway__heading__name'})
                    item_title = item_header.text.strip()
                    item_href = "%s%s" % (self.site_url, item_header['href'])

                    r = request.Request(item_href, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
                    html = request.urlopen(r).read().decode('utf-8')
                    page = bs4.BeautifulSoup(html, PARSER)
                    try:
                        btn_text = page.find('div', {'class': 'sidebar__entry-insert'}).text
                    except:
                        btn_text = page.find('div', {'class': 'sidebar__error'}).text.strip()
                        if btn_text == 'Not Enough Points':
                            raise ParserError(self.name, "%s." % btn_text)
                        else:
                            self.log.debug("Can't inter in giveaway.%s" % btn_text)
                            continue
                    else:
                        status = self._giveaway_entry(page)
                        if status == 200:
                            giveaways_inter.append({'title': item_title, 'href': item_href},)
                            self.log.info('Take part in «%s» giveaway.' % item_title)

            page = soup.find('div', {'class': 'pagination__navigation'}).find_all('a')[-1]
            if page.span.text == 'Next':
                i += 1
                params.update({'page': i})
            else:
                sow = False
                self.log.info('No more giveaways.')
                break

        return giveaways_inter

    def _reap(self):
        giveaways_win = []

        url = '%s/giveaways/won' % self.site_url

        r = request.Request(url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        html = request.urlopen(r).read().decode('utf-8')
        soup = bs4.BeautifulSoup(html, PARSER)

        items = soup.find('div', {'class': 'table__rows'}).find_all('div', {'class': 'table__row-outer-wrap'})

        for item in items:
            not_received = item.find('div', {'class': 'table__gift-feedback-received is-hidden'})
            if not_received:
                item_header = item.find('a', {'class': 'table__column__heading'})
                item_title = item_header.text.strip()
                item_href = "%s%s" % (self.site_url, item_header['href'])

                giveaways_win.append({'title': item_title, 'href': item_href},)

            else:
                continue

        return giveaways_win

    def _giveaway_entry(self, page):
        url = "%s/ajax.php" % self.site_url

        form = page.find('div', {'class': 'sidebar'}).find('form')
        xsrf_token = form.find('input', {'name': 'xsrf_token'})['value']
        do = 'entry_insert'
        code = form.find('input', {'name': 'code'})['value']

        data = parse.urlencode({'xsrf_token': xsrf_token, 'do': do, 'code': code})
        data = data.encode('ascii')

        r = request.Request(url, data=data, headers={'user-agent': USER_AGENT, 'cookie': self.cookies}, method='POST')
        status = request.urlopen(r).getcode()

        return status


class IndieGalaHarvester(Harvester):
    name = "IndieGala"
    verbose_name = "«Indie Gala»"
    site_url = "https://www.indiegala.com"
    check_tag = "span"
    check_type = "class"
    check_text = "account-email"
    cookies = {'auth': None, 'incap_ses_586_255598': None}

    def get_level(self):
        url = "%s/giveaways/get_user_level_and_coins" % self.site_url
        r = request.Request(url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        data = json.loads(request.urlopen(r).read().decode('utf-8'))

        try:
            if data['status'] == 'ok':
                return data['current_level']
            else:
                raise ParserError(self.name, "Can't get %s level" % self.verbose_name)
        except KeyError:
            raise ParserError(self.name, "Can't get %s level" % self.verbose_name)

    def get_coins(self):
        url = "%s/giveaways" % self.site_url
        r = request.Request(url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        html = request.urlopen(r).read().decode('utf-8')
        soup = bs4.BeautifulSoup(html, PARSER)

        coins = int(soup.find('span', {'id': 'silver-coins-menu'}).text)

        return coins

    def _sow(self):
        level = self.get_level()
        coins = self.get_coins()
        giveaways_inter = []
        sow = True

        url = '%s/giveaways' % self.site_url
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
            r = request.Request(r_url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
            html = request.urlopen(r).read().decode('utf-8')
            soup = bs4.BeautifulSoup(html, PARSER)

            items = soup.find('div', {'class': 'tickets-row'}).find_all('div', {'class': 'tickets-col'})
            for item in items:
                item_level = int(re.findall(r'\d', item.find('div', {'class': 'type-level-cont'}).find('div', {'class': 'spacer-v-5'}).next.strip())[0])
                coupon = item.find('aside', {'class': 'giv-coupon'})
                item_header = item.find('div', {'class': 'box_pad_5'}).h2.a
                item_title = item_header['title']
                item_href = "%s%s" % (self.site_url, item_header['href'])

                giv_id = item.find('div', {'class': 'ticket-right'}).div['rel']
                ticket_price = int(item.find('div', {'class': 'ticket-price'}).strong.text.strip())

                if level < item_level or not coupon:
                    continue

                elif not int(self.config['wishlist']):
                    if coins < ticket_price:
                        sow = False
                        raise ParserError(self.name, "Not Enough Coins.")
                    else:
                        resp = self._giveaway_entry(giv_id, ticket_price)
                        status = resp['status']
                        coins = resp['new_amount']
                        if status == 'ok':
                            giveaways_inter.append({'title': item_title, 'href': item_href},)
                            self.log.info('Take part in «%s» giveaway.' % item_title)

                else:
                    for wish in self.wishlist:
                        if re.escape(str.lower(item_title)) == re.escape(str.lower(wish["title"])):
                            if coins < ticket_price:
                                sow = False
                                raise ParserError(self.name, "Not Enough Coins.")
                            else:
                                resp = self._giveaway_entry(giv_id, ticket_price)
                                status = resp['status']
                                coins = resp['new_amount']
                                if status == 'ok':
                                    giveaways_inter.append({'title': item_title, 'href': item_href},)
                                    self.log.info('Take part in «%s» giveaway at %s page.' % (item_title, i))
                        else:
                            continue

            try:
                page = soup.find('div', {'class': 'page-nav'}).find_all('div', {'class': 'page-link-cont'})[-2].a
                i += 1
            except AttributeError:
                sow = False
                self.log.info('No more giveaways.')
                break

        return giveaways_inter

    def _reap(self):
        giveaways_win = []

        url = '%s/giveaways/library_completed' % self.site_url

        r = request.Request(url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        data = request.urlopen(r).read().decode('utf-8')
        data = json.loads(data)
        soup = bs4.BeautifulSoup(data['html'], PARSER)
        items = soup.find_all('ul', {'class': 'giveaways-completed-list'})[0].find_all('li')
        try:
            for item in items:
                r_url = '%s/giveaways/check_if_won' % self.site_url

                entry_id = item.find('input', {'name': 'entry_id'})['value']

                data = json.dumps({'entry_id': entry_id}).encode('utf-8')

                r = request.Request(r_url, data=data, headers={'user-agent': USER_AGENT, 'cookie': self.cookies}, method='POST')
                resp = request.urlopen(r).read().decode('utf-8')
        except TypeError:
            pass

        r = request.Request(url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        data = request.urlopen(r).read().decode('utf-8')
        data = json.loads(data)
        soup = bs4.BeautifulSoup(data['html'], PARSER)
        items = soup.find_all('ul', {'class': 'giveaways-completed-list'})[1].find_all('li')
        try:
            for item in items:
                if item.find('button', {'class': 'btn-open-leave-feedback-form'}):
                    item_header = item.find('a', {'title': 'View giveaway details'})
                    item_title = item_header.text.strip()
                    item_href = "%s%s" % (self.site_url, item_header['href'])

                    giveaways_win.append({'title': item_title, 'href': item_href},)

                else:
                    continue

        except TypeError:
            pass

        return giveaways_win

    def _giveaway_entry(self, giv_id, ticket_price):
        url = '%s/giveaways/new_entry' % self.site_url

        data = json.dumps({'giv_id': giv_id, 'ticket_price': ticket_price}).encode('utf-8')

        r = request.Request(url, data=data, headers={'user-agent': USER_AGENT, 'cookie': self.cookies}, method='POST')
        resp = request.urlopen(r).read().decode('utf-8')
        resp = json.loads(resp)

        return resp


def spawner(name, queue, wishlist, log_level):
    log = logging.getLogger(name)

    if not log.hasHandlers():
        formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s][%(processName)s]: %(message)s',
                                      "%Y-%m-%d %H:%M:%S")
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        log.addHandler(console)

    log.setLevel(log_level)

    try:
        if name == "SteamGifts":
            harvester = SteamGiftsHarvester(wishlist, log_level)
            results = harvester.start()

            queue.put(results)

        elif name == "IndieGala":
            harvester = IndieGalaHarvester(wishlist, log_level)
            results = harvester.start()

            queue.put(results)

    except FileNotFoundError:
        log.error("No config file. Please copy «giveaway_bot.exp» as «giveaway_bot.ini» and edit it.")
        harvester._stop()
    except ParserError:
        harvester._stop()
    except error.HTTPError as e:
        log.error('HTTP error code %s: %s' % (e.code, e.msg))
        harvester._stop()

def main():
    opt_parser = OptionParser()
    opt_parser.add_option("--debug", action="store_true", dest="debug", default=False, help="Enable debug messanges")
    options, args = opt_parser.parse_args()

    log = logging.getLogger('Main')
    if not log.hasHandlers():
        formatter = logging.Formatter('[%(asctime)s][%(levelname)s][%(name)s][%(processName)s]: %(message)s', "%Y-%m-%d %H:%M:%S")
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        log.addHandler(console)

    if options.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    log.setLevel(log_level)

    log.info("WELCOME TO GIVEAWAY BOT REBORN")

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
            log.info("In wishlist %s games" % len(bot.wishlist))
            for i in range(int(config['sleepTime'])):
                processes_logs = bot.processes_logs
                for key in bot.processes_logs:
                    queue = bot.processes_logs[key]
                    while not queue.empty():
                        results = queue.get()
                        if len(results['reap']) > 0:
                            log.info('[%(timestamp)s] %(key)s Harvester end work takes part in %(num)s giveaways, and you have win something.' %
                                     {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key, 'num': len(results['sow'])})
                        else:
                            log.info("[%(timestamp)s] %(key)s Harvester end work: takes part in %(num)s giveaways, and you don't win anything. For now..." %
                                     {'timestamp': results['timestamp'].strftime("%Y-%m-%d %H:%M:%S"), 'key': key, 'num': len(results['sow'])})

                time.sleep(60)

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
            bot.stop()
        except Error:
            bot.stop()

if __name__ == '__main__':
    main()