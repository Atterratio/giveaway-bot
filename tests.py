import unittest
import multiprocessing
import random

from giveaway_bot import SteamParser, Harvester, Giveaway
from giveaway_bot import SteamGiftsHarvester, SteamGiftsGiveaway
from giveaway_bot import IndieGalaHarvester, IndieGalaGiveaway

class SteamParserTestCase(unittest.TestCase):
    def setUp(self):
        self.queue = multiprocessing.Queue()
        self.log_level = 100
        self.steam = SteamParser(self.queue, self.log_level)

    def test_singleton(self):
        steam = SteamParser(self.queue, self.log_level)
        self.assertEqual(id(self.steam), id(steam))

    def test_login_check(self):
        loged_html = '<a class="user_avatar"></a>'
        with self.assertLogs(self.steam.name, level='DEBUG') as log:
            self.steam._login_check(loged_html)
            self.assertIn('login successful', log.output[0])

    def test_wishlist(self):
        wishlist = self.steam.wishlist
        self.assertIsNotNone(wishlist)
        self.assertIsInstance(wishlist, list)
        self.assertGreater(len(wishlist), 0)

        random_item = wishlist[random.randint(0, len(wishlist)-1)]
        self.assertIn('id', random_item)
        self.assertIs(type(random_item['id']), int)
        self.assertIn('title', random_item)
        self.assertIs(type(random_item['title']), str)

    def test_library(self):
        library = self.steam.library
        self.assertIsNotNone(library)
        self.assertIsInstance(library, list)
        self.assertGreater(len(library), 0)

        random_item = library[random.randint(0, len(library)-1)]
        self.assertIn('appid', random_item)
        self.assertIsInstance(random_item['appid'], int)
        self.assertIn('name', random_item)
        self.assertIsInstance(random_item['name'], str)

    def test_get_os_list(self):
        # TODO find mo test excamples
        id_630 = self.steam.get_os_list(630)
        self.assertIsInstance(id_630, list)
        self.assertEqual(id_630, ['win'])

        id_500 = self.steam.get_os_list(500)
        self.assertIsInstance(id_500, list)
        self.assertEqual(id_500, ['win', 'mac'])

        id_400 = self.steam.get_os_list(400)
        self.assertIsInstance(id_400, list)
        self.assertEqual(id_400, ['win', 'lin', 'mac'])

    def test_get_type(self):
        id_620 = self.steam.get_type(620)
        self.assertIsInstance(id_620, str)
        self.assertEqual(id_620, 'game')

        id_323180 = self.steam.get_type(323180)
        self.assertIsInstance(id_323180, str)
        self.assertEqual(id_323180, 'dlc')

    def test_get_cards(self):
        id_271590 = self.steam.get_cards(271590)
        self.assertIsInstance(id_271590, bool)
        self.assertEqual(id_271590, False)

        id_8930 = self.steam.get_cards(8930)
        self.assertIsInstance(id_8930, bool)
        self.assertEqual(id_8930, True)

    def test_get_title(self):
        id_8930 = self.steam.get_title(8930)
        self.assertIsInstance(id_8930, str)
        self.assertEqual(id_8930, "Sid Meier's Civilization® V")

        id_250900 = self.steam.get_title(250900)
        self.assertIsInstance(id_250900, str)
        self.assertEqual(id_250900, "The Binding of Isaac: Rebirth")


class HarvesterTestCase(unittest.TestCase):
    def setUp(self):
        self.queue = multiprocessing.Queue()
        TestGiveaway = type('TestGiveaway', (Giveaway, ), {'enter': lambda s: 'ok'})
        TestGiveaway.name = 'Steam'

        self.gw_list = []

        def set_gw_attribs(gw, **kwargs):
            gw.cached_in_library = False
            gw.cached_in_wishlist = True
            gw.title = 'Default'
            gw.href = 'http://example.com/'
            gw.entered = False
            gw.level = 1
            gw.points = 11
            gw.trust_points = 1
            gw.cached_os_list = ['win', 'lin', 'mac']
            gw.cached_dlc = False
            gw.cached_cards = True

            self.gw_list.append(gw)

            for key in kwargs:
                setattr(gw, key, kwargs[key])

        self.gw_default = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_default)

        self.gw_lib = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_lib, cached_in_library=True, title='Game In Library')

        self.gw_wish = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_wish, cached_in_wishlist=False, title='Game Not In Wishlist')

        self.gw_enter = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_enter, entered=True, title='Already In Giveaway')

        self.gw_height_level = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_height_level, level='5', title='To height level')

        self.gw_low_level = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_low_level, level='0', title='To low level')

        self.gw_expensive = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_expensive, points='100', title='To expensive')

        self.gw_chip = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_chip, points='5', title='To chip')

        self.gw_trust_zero = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_trust_zero, trust_points='0', title='Zero trust')

        self.gw_trust_negative = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_trust_negative, trust_points='-1', title='Negative trust')

        self.gw_win = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_win, cached_os_list=['lin', 'mac'], title='Not support Windows')

        self.gw_lin = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_lin, cached_os_list=['win', 'mac'], title='Not support Linix')

        self.gw_mac = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_mac, cached_os_list=['win', 'lin'], title='Not support Mac')

        self.gw_dlc = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_dlc, cached_dlc=True, title='This is TRAP!')

        self.gw_cards = TestGiveaway(self.queue, 100, 0)
        set_gw_attribs(self.gw_cards, cached_cards=False, title='No cards')

        def _get_giveaways(hw, page):
            if page == 1:
                return self.gw_list
            else:
                return []

        self.TestHarvester = type('TestHarvester', (Harvester,), {'_get_giveaways': _get_giveaways, '_reap': '', 'level': 1, 'points': 30})
        self.TestHarvester.name = 'Steam'
        self.hw = self.TestHarvester(self.queue, 100)
        self.hw.filters = ['entered', 'level', 'library', 'wishlist', 'dlc', 'cards', ['trust', '0'],
                           'trust', ['max_points', '50'], ['min_points', '10'], ['min_level', '1'], ['os', 'lin']]

    def test_sow(self):
        giveaways_enter = self.hw._sow()
        self.assertIsInstance(giveaways_enter, list)
        self.assertEqual(len(giveaways_enter), 2)
        for giveaway in giveaways_enter:
            self.assertEqual(len(giveaway), 2)
            self.assertIn('title', giveaway)
            self.assertIn('href', giveaway)


    def test_filter_trust(self):
        gw_list_trust = self.hw._filter_trust(self.gw_list)
        self.assertIsInstance(gw_list_trust, list)
        self.assertEqual(len(gw_list_trust), 13)
        self.assertNotIn(self.gw_trust_zero, gw_list_trust)
        self.assertNotIn(self.gw_trust_negative, gw_list_trust)

        gw_list_trust_plus = self.hw._arged_filter_trust(self.gw_list, 1)
        self.assertIsInstance(gw_list_trust_plus, list)
        self.assertEqual(len(gw_list_trust_plus), 13)
        self.assertNotIn(self.gw_trust_zero, gw_list_trust_plus)
        self.assertNotIn(self.gw_trust_negative, gw_list_trust_plus)

        gw_list_trust_zero = self.hw._arged_filter_trust(self.gw_list, 0)
        self.assertIsInstance(gw_list_trust_zero, list)
        self.assertEqual(len(gw_list_trust_zero), 14)
        self.assertIn(self.gw_trust_zero, gw_list_trust_zero)
        self.assertNotIn(self.gw_trust_zero, gw_list_trust_plus)

        gw_list_trust_all = self.hw._arged_filter_trust(self.gw_list, -1)
        self.assertIsInstance(gw_list_trust_all, list)
        self.assertEqual(len(gw_list_trust_all), 15)
        self.assertIn(self.gw_trust_zero, gw_list_trust_all)
        self.assertIn(self.gw_trust_negative, gw_list_trust_all)

    def test_arged_filter_max_points(self):
        gw_list = self.hw._arged_filter_max_points(self.gw_list, 50)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_expensive, gw_list)

    def test_arged_filter_max_points(self):
        gw_list = self.hw._arged_filter_min_points(self.gw_list, 10)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_chip, gw_list)

    def test_filter_level(self):
        gw_list = self.hw._filter_level(self.gw_list)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_height_level, gw_list)

    def test_arged_filter_min_level(self):
        gw_list = self.hw._arged_filter_min_level(self.gw_list, 1)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_low_level, gw_list)

    def test_arged_filter_os(self):
        gw_list_win = self.hw._arged_filter_os(self.gw_list, 'win')
        self.assertIsInstance(gw_list_win, list)
        self.assertEqual(len(gw_list_win), 14)
        self.assertNotIn(self.gw_win, gw_list_win)

        gw_list_lin = self.hw._arged_filter_os(self.gw_list, 'lin')
        self.assertIsInstance(gw_list_lin, list)
        self.assertEqual(len(gw_list_lin), 14)
        self.assertNotIn(self.gw_lin, gw_list_lin)

        gw_list_mac = self.hw._arged_filter_os(self.gw_list, 'mac')
        self.assertIsInstance(gw_list_mac, list)
        self.assertEqual(len(gw_list_mac), 14)
        self.assertNotIn(self.gw_mac, gw_list_mac)

    def test_filter_entered(self):
        gw_list = self.hw._filter_entered(self.gw_list)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_enter, gw_list)

    def test_filter_library(self):
        gw_list = self.hw._filter_library(self.gw_list)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_lib, gw_list)

    def test_filter_wishlist(self):
        gw_list = self.hw._filter_wishlist(self.gw_list)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_wish, gw_list)

    def test_filter_dlc(self):
        gw_list = self.hw._filter_dlc(self.gw_list)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_dlc, gw_list)

    def test_filter_cards(self):
        gw_list = self.hw._filter_cards(self.gw_list)
        self.assertIsInstance(gw_list, list)
        self.assertEqual(len(gw_list), 14)
        self.assertNotIn(self.gw_cards, gw_list)


class GiveawayTestCase(unittest.TestCase):
    def setUp(self):
        queue = multiprocessing.Queue()
        TestGiveaway = type('TestGiveaway', (Giveaway, ), {'enter': ''})
        TestGiveaway.name = 'Steam'
        self.libed = TestGiveaway(queue, 100, 337420)
        self.wished = TestGiveaway(queue, 100, 271590)
        self.dlc = TestGiveaway(queue, 100, 235580)

    def test_in_wishlist(self):
        self.assertIsInstance(self.libed.in_wishlist, bool)
        self.assertEqual(self.libed.in_wishlist, False)

        self.assertIsInstance(self.wished.in_wishlist, bool)
        self.assertEqual(self.wished.in_wishlist, True)

        self.assertIsInstance(self.dlc.in_wishlist, bool)
        self.assertEqual(self.dlc.in_wishlist, False)

    def test_in_library(self):
        self.assertIsInstance(self.libed.in_library, bool)
        self.assertEqual(self.libed.in_library, True)

        self.assertIsInstance(self.wished.in_library, bool)
        self.assertEqual(self.wished.in_library, False)

        self.assertIsInstance(self.dlc.in_library, bool)
        self.assertEqual(self.dlc.in_library, True)

    def test_os_list(self):
        self.assertIsInstance(self.libed.os_list, list)
        self.assertEqual(self.libed.os_list, ['win'])

        self.assertIsInstance(self.wished.os_list, list)
        self.assertEqual(self.wished.os_list, ['win'])

        self.assertIsInstance(self.dlc.os_list, list)
        self.assertEqual(self.dlc.os_list, ['win', 'lin', 'mac'])

    def test_dlc(self):
        self.assertIsInstance(self.libed.dlc, bool)
        self.assertEqual(self.libed.dlc, False)

        self.assertIsInstance(self.wished.dlc, bool)
        self.assertEqual(self.wished.dlc, False)

        self.assertIsInstance(self.dlc.dlc, bool)
        self.assertEqual(self.dlc.dlc, True)

    def test_cards(self):
        self.assertIsInstance(self.libed.cards, bool)
        self.assertEqual(self.libed.cards, True)

        self.assertIsInstance(self.wished.cards, bool)
        self.assertEqual(self.wished.cards, False)

        self.assertIsInstance(self.dlc.cards, bool)
        self.assertEqual(self.dlc.cards, False)


class SteamGiftsHarvesterTestCase(unittest.TestCase):
    def setUp(self):
        queue = multiprocessing.Queue()
        log_level = 100
        self.harvester = SteamGiftsHarvester(queue, log_level)

    def test_login_check(self):
        loged_html = '<div class="nav__avatar-inner-wrap"></div>'
        with self.assertLogs(self.harvester.name, level='DEBUG') as log:
            self.harvester._login_check(loged_html)
            self.assertIn('login successful', log.output[0])

    def test_level(self):
        level = self.harvester.level
        self.assertIsInstance(level, int)
        self.assertEqual(level, 1)

    def test_points(self):
        points = self.harvester.points
        self.assertIsInstance(points, int)
        self.assertGreaterEqual(points, 0)


class SteamGiftsGiveawayTestCase(unittest.TestCase):
    def setUp(self):
        queue = multiprocessing.Queue()
        log_level = 100
        self.giveaway = SteamGiftsGiveaway(queue, log_level, 0,  0, 0, 'Test SteamGifts Giveaway', '', False, 1, 1, 'https://www.steamgifts.com/user/Atterratio')

    def test_trust_points(self):
        trust_points = self.giveaway.trust_points
        self.assertIsInstance(trust_points, int)
        self.assertGreater(trust_points, 0)


class IndieGalaHarvesterTestCase(unittest.TestCase):
    def setUp(self):
        queue = multiprocessing.Queue()
        log_level = 100
        self.harvester = IndieGalaHarvester(queue, log_level)

    def test_login_check(self):
        loged_html = '<span class="account-email"></span>'
        with self.assertLogs(self.harvester.name, level='DEBUG') as log:
            self.harvester._login_check(loged_html)
            self.assertIn('login successful', log.output[0])

    def test_level(self):
        level = self.harvester.level
        self.assertIsInstance(level, int)
        self.assertEqual(level, 0)

    def test_points(self):
        points = self.harvester.points
        self.assertIsInstance(points, int)
        self.assertGreaterEqual(points, 0)


class IndieGalaGiveawayTestCase(unittest.TestCase):
    def setUp(self):
        queue = multiprocessing.Queue()
        log_level = 100
        self.giveaway = IndieGalaGiveaway(queue, log_level, 173421, 'Polarity', 'https://www.indiegala.com/giveaways/detail/173421', False, 0, 1, 'https://www.indiegala.com/trades/user/f6f6f4abaff711e591621788afad681a')

    def test_trust_points(self):
        trust_points = self.giveaway.trust_points
        self.assertIsInstance(trust_points, int)
        self.assertGreater(trust_points, 0)

    def test_in_library(self):
        in_library = self.giveaway.in_library
        self.assertIsInstance(in_library, bool)
        self.assertIs(in_library, True)

    def test_game_id(self):
        game_id = self.giveaway.game_id
        self.assertIsInstance(game_id, int)
        self.assertEqual(game_id, 315430)


if __name__ == '__main__':
    unittest.main(verbosity=2)