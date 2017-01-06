#!/usr/bin/env python3

import os
import sys
import logging
import configparser
import requests
import time
import multiprocessing

import bs4

from datetime import datetime
from optparse import OptionParser
from urllib import request, parse

from ghost import Ghost

try:
    import lxml
except:
    PARSER = "html.parser"
else:
    PARSER = "lxml"

os.chdir(os.path.dirname(__file__))

USER_AGENT = 'Mozilla/5.0'


class Error(Exception):
    def __init__(self, name, message):
        log = logging.getLogger(name)
        log.error(message)


class ParserError(Error):
    pass


class GiveawayBot:
    def __init__(self, log_level):
        self.log_level = log_level
        self.log = logging.getLogger('Bot')
        if not self.log.hasHandlers():
            formatter = logging.Formatter('[%(asctime)s][%(name)s][%(processName)s][%(levelname)s]: %(message)s', "%Y-%m-%d %H:%M:%S")
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            self.log.addHandler(console)
        self.log.setLevel(self.log_level)

        self.parsers = [{"name": "Steam"}, {"name": "SteamGifts"}, {"name": "IndieGala"}]

        self.wishlist = None
        self.processes_logs = {}

    def start(self):
        for parser in self.parsers:
            if parser['name'] == "Steam":
                prs = SteamParser(self.log_level)
                self.wishlist = prs.start()
            else:
                queue = multiprocessing.Queue()
                self.processes_logs.update({parser['name']: queue})
                process = multiprocessing.Process(target=spawner, args=(parser['name'], queue, self.log_level), name=parser['name'])
                process.start()

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
            formatter = logging.Formatter('[%(asctime)s][%(name)s][%(processName)s][%(levelname)s]: %(message)s', "%Y-%m-%d %H:%M:%S")
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            self.log.addHandler(console)
        self.log.setLevel(log_level)

        config = configparser.ConfigParser()
        try:
            config.read_file(open("giveaway_bot.ini"))
        except FileNotFoundError:
            self.log.error("No config file. Please copy «giveaway_bot.exp» as «giveaway_bot.ini» and edit it.")
            sys.exit()
        self.config = config[self.name]

        cookies_str = ''
        for key in self.cookies:
            cookies_str += '%s=%s;' % (key, self.config[key])

        self.cookies = cookies_str

    def start(self):
        self.log.info("Starting %s parser" % self.verbose_name)
        self._login_check()
        results = self._main()
        self.log.info("Stoping %s parser" % self.verbose_name)

        return results

    def _main(self):
        pass

    def _login_check(self):
        r = request.Request(self.site_url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        html = str(request.urlopen(r).read())
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
        html = str(request.urlopen(r).read())
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

            data = {'num': i, 'id': str.strip(item['id'], 'game_'), 'name': item.find('h4', {'class': 'ellipsis'}).text,
                    'logo': item.a.img['src'], 'page': item.find('div', {'class': 'storepage_btn_ctn'}).a['href'],
                    'price': price, 'price_old': price_old}

            list.append(data)

        self.log.info('In Steam Wishlist %s games' % len(list))

        for game in self.config['wishlist'].split('; '):
            list.append({'name': game})

        return list


class Harvester(Parser):

    def start(self):
        self.log.info("Starting %s harvester" % self.verbose_name)
        self._login_check()
        results = self._main()
        self.log.info("Stoping %s harvester" % self.verbose_name)

        return results

    def _main(self):
        self.log.info("Startind %s sow" % self.verbose_name)
        sow = self._sow()
        self.log.info("Stoping %s sow" % self.verbose_name)

        self.log.info("Startind %s reap" % self.verbose_name)
        reap = self._reap()
        self.log.info("Stoping %s reap" % self.verbose_name)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        results = {'timestamp': timestamp, 'sow': sow, 'reap': reap}

        return results

    def _sow(self):
        giveaways_inter = ({'title': None, 'href': None},)

        return giveaways_inter

    def _reap(self):
        giveaways_win = ({'title': None, 'href': None},)

        return giveaways_win


class SteamGiftsParser(Harvester):
    name = "SteamGifts"
    verbose_name = "«Steam Gifts»"
    site_url = "https://www.steamgifts.com/"
    check_tag = "div"
    check_type = "class"
    check_text = "nav__avatar-inner-wrap"
    cookies = {'PHPSESSID': None}

    def _sow(self):
        giveaways_inter = []
        params = {}
        sowing = True

        if int(self.config['wishlist']):
            url = '%sgiveaways/search' % self.site_url
            params.update({'type': 'wishlist'})
        else:
            url = self.site_url

        while sowing:
            r_url = "%s?" % url
            for key in params:
                r_url = '%s%s=%s&' % (r_url, key, params[key])

            r = request.Request(r_url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
            html = str(request.urlopen(r).read())
            soup = bs4.BeautifulSoup(html, PARSER)

            items = soup.find('div', {'class': 'page__heading'}).next_sibling.next_sibling.find_all('div', {'class': 'giveaway__row-outer-wrap'})
            for item in items:
                if item.find('div', {'class': 'is-faded'}):
                    continue
                else:
                    item_header = item.find('a', {'class': 'giveaway__heading__name'})
                    item_title = item_header.text.strip()
                    item_href = "%s%s" % (self.site_url, item_header['href'])

                    ajax_url = "%sajax.php" % self.site_url

                    r = request.Request(item_href, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
                    html = str(request.urlopen(r).read())
                    page = bs4.BeautifulSoup(html, PARSER)
                    try:
                        btn_text = page.find('div', {'class': 'sidebar__entry-insert'}).text
                    except:
                        btn_text = page.find('div', {'class': 'sidebar__error'}).text.strip()
                        if btn_text == 'Not Enough Points':
                            sowing = False
                            self.log.warning("%s." % btn_text)
                            break
                        else:
                            self.log.debug("Can't inter in giveawat.%s" % btn_text)
                            continue
                    else:
                        form = page.find('div', {'class': 'sidebar'}).find('form')
                        xsrf_token = form.find('input', {'name': 'xsrf_token'})['value']
                        do = 'entry_insert'
                        code = form.find('input', {'name': 'code'})['value']

                        data = parse.urlencode({'xsrf_token': xsrf_token, 'do': do, 'code': code})
                        data = data.encode('ascii')

                        r = request.Request(ajax_url, data=data, headers={'user-agent': USER_AGENT, 'cookie': self.cookies}, method='POST')
                        status = request.urlopen(r).getcode()
                        if status == 200:
                            giveaways_inter.append({'title': item_title, 'href': item_href},)
                            self.log.info('Take part in %s game giveaway.' % item_title)

            page = soup.find('div', {'class': 'pagination__navigation'}).find_all('a')[-1]
            if page.span.text == 'Next':
                params.update({'page': int(page['data-page-number'])})
            else:
                sowing = False
                self.log.warning('No more giveaways.')
                break

        return giveaways_inter

    def _reap(self):
        giveaways_win = []

        url = '%sgiveaways/won' % self.site_url

        r = request.Request(url, headers={'user-agent': USER_AGENT, 'cookie': self.cookies})
        html = str(request.urlopen(r).read())
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


def spawner(name, queue, log_level):
    if name == "SteamGifts":
        harvester = SteamGiftsParser(log_level)
        results = harvester.start()

        queue.put(results)


def main():
    opt_parser = OptionParser()
    opt_parser.add_option("--debug", action="store_true", dest="debug", default=False, help="Enable debug messanges")
    options, args = opt_parser.parse_args()

    log = logging.getLogger('Main')
    formatter = logging.Formatter('[%(asctime)s][%(name)s][%(processName)s][%(levelname)s]: %(message)s', "%Y-%m-%d %H:%M:%S")
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
                            log.info('At %(timestamp)s Harvester end work takes part in %(num)s giveaways, and you have win something.' %
                                     {'timestamp': results['timestamp'], 'num': len(results['sow'])})
                        else:
                            log.info("At %(timestamp)s Harvester end work: takes part in %(num)s giveaways, and you don't win anything at for now." %
                                     {'timestamp': results['timestamp'], 'num': len(results['sow'])})

                time.sleep(60)

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
            bot.stop()
        except Error:
            bot.stop()

if __name__ == '__main__':
    main()