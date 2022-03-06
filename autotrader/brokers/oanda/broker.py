import v20
import sys
import time
import datetime
import traceback
import numpy as np
import pandas as pd
from autotrader.brokers.broker_utils import BrokerUtils
from autotrader.brokers.trading import Order, Trade, Position


class Broker:
    def __init__(self, oanda_config: dict, utils: BrokerUtils):
        """Create v20 context.
        """
        self.API = oanda_config["API"]
        self.ACCESS_TOKEN = oanda_config["ACCESS_TOKEN"]
        self.port = oanda_config["PORT"]
        self.ACCOUNT_ID = oanda_config["ACCOUNT_ID"]
        self.api = v20.Context(hostname = self.API, 
                               token = self.ACCESS_TOKEN, 
                               port = self.port)
        
        self.STREAM_API = "stream-fxpractice.oanda.com"
        self.stream = v20.Context(hostname = self.STREAM_API, 
                                  token = self.ACCESS_TOKEN, 
                                  port = self.port)
        self.open_positions = {}
        self.utils = utils
        
    
    def __repr__(self):
        return 'AutoTrader-Oanda Broker Interface'
    
    
    def __str__(self):
        return 'AutoTrader-Oanda Broker Interface'
    
    
    def get_NAV(self) -> float:
        """Returns Net Asset Value of account.
        """
        self._check_connection()
        response = self.api.account.get(accountID=self.ACCOUNT_ID)
        return response.body["account"].NAV
    
    
    def get_balance(self) -> float:
        """Returns account balance.
        """
        self._check_connection()
        response = self.api.account.get(accountID=self.ACCOUNT_ID)
        return response.body["account"].balance
    
    
    def place_order(self, order: Order, **kwargs):
        """Submits order to broker.
        """
        self._check_connection()
        
        # Assign order_time, order_price, HCF
        price_data = self._get_price(instrument=order.instrument)
        order_price = price_data['ask'] if order.direction > 0 else price_data['bid']
        HCF = price_data['positiveHCF'] if order.direction > 0 else price_data['negativeHCF']

        # Call order with price and time
        order(broker=self, order_price=order_price, HCF=HCF)
        
        # Submit order
        if order.order_type == 'market':
            response = self._place_market_order(order)
        elif order.order_type == 'stop-limit':
            response = self._place_stop_limit_order(order)
        elif order.order_type == 'limit':
            response = self._place_limit_order(order)
        elif order.order_type == 'close':
            response = self._close_position(order.instrument)
        else:
            print("Order type not recognised.")
        
        # Check response
        # output = self._check_response(response)
        
        return response
        
    
    def get_orders(self, instrument=None, **kwargs) -> dict:
        """Get all pending orders in the account. 
        """
        self._check_connection()
        response = self.api.order.list_pending(accountID=self.ACCOUNT_ID, 
                                               instrument=instrument)
        oanda_pending_orders = response.body['orders']
        orders = {}
        
        for order in oanda_pending_orders:
            if order.type != 'TAKE_PROFIT' and order.type != 'STOP_LOSS':
                new_order = {}
                new_order['id'] = order.id
                new_order['status'] = 'open'
                new_order['order_type'] = order.type
                new_order['order_stop_price'] = order.price
                new_order['order_limit_price'] = order.price
                new_order['direction'] = np.sign(order.units)
                new_order['order_time'] = order.createTime
                new_order['instrument'] = order.instrument
                new_order['size'] = order.units
                new_order['order_price'] = order.price
                new_order['take_profit'] = order.takeProfitOnFill.price if order.takeProfitOnFill is not None else None
                new_order['take_distance'] = None
                new_order['stop_loss'] = None # TODO - include
                new_order['stop_type'] = None
                new_order['stop_distance'] = None
                new_order['related_orders'] = None
                
                if instrument is not None and order.instrument == instrument:
                    orders[order.id] = Order._from_dict(new_order)
                elif instrument is None:
                    orders[order.id] = Order._from_dict(new_order)
            
        return orders
    
    
    def cancel_order(self, order_id: int, **kwargs) -> None:
        """Cancels pending order by ID.
        """
        self._check_connection()
        self.api.order.cancel(accountID = self.ACCOUNT_ID, 
                              orderSpecifier=str(order_id))
    
    
    def get_trades(self, instruments=None, **kwargs) -> dict:
        """Returns the open trades held by the account. 
        
        (incomplete implementation)
        """
        self._check_connection()
        response = self.api.trade.list_open(accountID=self.ACCOUNT_ID)
        oanda_open_trades = response.body['trades']
        
        open_trades = {}
        for trade in oanda_open_trades:
            new_trade = {}
            new_trade['order_ID']           = trade.id
            new_trade['order_stop_price']   = trade.price
            new_trade['order_limit_price']  = trade.price
            new_trade['direction']          = np.sign(trade.currentUnits)
            new_trade['order_time']         = trade.openTime
            new_trade['instrument']         = trade.instrument
            new_trade['size']               = trade.currentUnits
            new_trade['order_price']        = trade.price
            new_trade['entry_price']        = trade.price
            new_trade['order_type']         = None
            new_trade['strategy']           = None
            new_trade['granularity']        = None
            new_trade['take_profit']        = None
            new_trade['take_distance']      = None
            new_trade['stop_type']          = None
            new_trade['stop_distance']      = None
            new_trade['stop_loss']          = None
            new_trade['related_orders']     = None
            
            if instruments is not None and trade.instrument in instruments:
                open_trades[trade.id] = Trade(new_trade)
            elif instruments is None:
                open_trades[trade.id] = Trade(new_trade)
        
        return open_trades
    
    
    def get_trade_details(self, trade_ID: int):
        """Returns the details of the trade specified by trade_ID.
        """
        response = self.api.trade.list(accountID=self.ACCOUNT_ID, ids=int(trade_ID))
        trade = response.body['trades'][0]
        
        details = {'direction': int(np.sign(trade.currentUnits)), 
                   'order_time': datetime.datetime.strptime(trade.openTime[:-4],
                                                            '%Y-%m-%dT%H:%M:%S.%f'), 
                   'instrument': trade.instrument, 
                   'size': trade.currentUnits,
                   'order_price': trade.price, 
                   'order_ID': trade.id, 
                   'time_filled': trade.openTime, 
                   'entry_price': trade.price, 
                   'unrealised_PL': trade.unrealizedPL, 
                   'margin_required': trade.marginUsed}
        
        # Get associated trades
        related = []
        try:
            details['take_profit'] = trade.takeProfitOrder.price
            related.append(trade.takeProfitOrder.id)
        except:
            pass
        
        try:
            details['stop_loss'] = trade.stopLossOrder.price
            related.append(trade.stopLossOrder.id)
        except:
            pass
        details['related_orders'] = related
        
        return Trade(trade)
    
    
    def get_positions(self, instrument: str = None, **kwargs) -> dict:
        """Gets the current positions open on the account. 
        """
        self._check_connection()
        response = self.api.position.list_open(accountID=self.ACCOUNT_ID)
        oanda_open_positions = response.body['positions']
        open_positions = {}
        for position in oanda_open_positions:
            pos = {'instrument': position.instrument,
                   'long_units': position.long.units,
                   'long_PL': position.long.unrealizedPL,
                   'long_margin': None,
                   'short_units': position.short.units,
                   'short_PL': position.short.unrealizedPL,
                   'short_margin': None,
                   'total_margin': position.marginUsed}
            
            # fetch trade ID'strade_IDs
            trade_IDs = []
            if abs(pos['long_units']) > 0: 
                for ID in position.long.tradeIDs: trade_IDs.append(ID)
            if abs(pos['short_units']) > 0: 
                for ID in position.short.tradeIDs: trade_IDs.append(ID)
            
            pos['trade_IDs'] = trade_IDs
            
            if instrument is not None and position.instrument == instrument:
                open_positions[position.instrument] = Position(**pos)
            elif instrument is None:
                open_positions[position.instrument] = Position(**pos)
        
        return open_positions
    
    
    def get_position(self, instrument: str) -> Position:
        """Gets position from Oanda.
        """
        self._check_connection()
        response = self.api.position.get(instrument = instrument, 
                                         accountID = self.ACCOUNT_ID)
        # TODO - convert to position
        return response.body['position']
    
    
    def get_summary(self):
        """Returns account summary.
        """
        self._check_connection()
        # response = self.api.account.get(accountID=self.ACCOUNT_ID)
        response = self.api.account.summary(accountID=self.ACCOUNT_ID)
        return response
    
    
    def get_data(self, pair: str, period: int, interval: str) -> pd.DataFrame:
        self._check_connection()
        response = self.api.instrument.candles(pair, granularity=interval,
                                               count=period, dailyAlignment = 0)
        data = self.utils.response_to_df(response)
        return data
    
    
    def check_trade_size(self, instrument: str, units: float) -> float:
        """Checks the requested trade size against the minimum trade size 
        allowed for the currency pair.
        """
        response = self.api.account.instruments(accountID=self.ACCOUNT_ID, 
                                                instruments = instrument)
        # minimum_units = response.body['instruments'][0].minimumTradeSize
        trade_unit_precision = response.body['instruments'][0].tradeUnitsPrecision
        return round(units, trade_unit_precision)
    
    
    def update_data(self, instrument: str, granularity: str, 
                    data: pd.DataFrame) -> pd.DataFrame:
        """Attempts to construct the latest candle when there is a delay in the 
        api feed.
        """
        self._check_connection()
        granularity_details = self.deconstruct_granularity(granularity)
        secs = granularity_details['seconds']
        mins = granularity_details['minutes']
        hrs  = granularity_details['hours']
        days = granularity_details['days']
        
        small_granularity = self.get_reduced_granularity(granularity_details, 25)
        
        # Get data equivalent of last candle's granularity
        time_now = datetime.datetime.now()
        start_time = time_now - datetime.timedelta(seconds = secs,
                                                   minutes = mins,
                                                   hours = hrs,
                                                   days = days)
        latest_data = self.get_historical_data(instrument, 
                                               small_granularity, 
                                               start_time.timestamp(), 
                                               time_now.timestamp())
        
        # Get latest price data
        latest_close = latest_data.Close.values[0]
        
        open_price = data.Close.values[-1]
        close_price = latest_close
        high_price = max(latest_data.High.values)
        low_price = min(latest_data.Low.values)
        last_time = data.index[-1]
        stripped_time = datetime.datetime.strptime(last_time.strftime("%Y-%m-%d %H:%M:%S%z"),
                                                      "%Y-%m-%d %H:%M:%S%z")
        new_time = stripped_time + datetime.timedelta(seconds = secs,
                                                      minutes = mins,
                                                      hours = hrs,
                                                      days = days)
        
        new_candle = pd.DataFrame({'Open'  : open_price, 
                                   'High'  : high_price,
                                   'Low'   : low_price,
                                   'Close' : close_price},
                                  index=[new_time])
        
        new_data = pd.concat([data, new_candle])
        
        return new_data
    
    
    def get_historical_data(self, instrument, interval, from_time, to_time):
        
        self._check_connection()
        
        response        = self.api.instrument.candles(instrument,
                                                      granularity = interval,
                                                      fromTime = from_time,
                                                      toTime = to_time
                                                      )
        
        data = self.utils.response_to_df(response)
        
        return data
    
    
    def deconstruct_granularity(self, granularity: str):
        """Returns a dict with the seconds, minutes, hours and days
        corresponding to a granularity. 
        """
        
        # Get letter to determine timeframe (eg. M)
        letter = granularity[0]
        
        # Get timeframe multiple (eg. 15)
        if len(granularity) > 1:
            number = float(granularity[1:])
        else:
            number = 1
        
        
        if letter == 'S':
            seconds     = number
            minutes     = 0
            hours       = 0
            days        = 0
        
        elif letter == 'M':
            seconds     = 0
            minutes     = number
            hours       = 0
            days        = 0
            
        elif letter == 'H':
            seconds     = 0
            minutes     = 0
            hours       = number
            days        = 0
            
        else:
            seconds     = 0
            minutes     = 0
            hours       = 0
            days        = number
        
        granularity_details = {'seconds': seconds,
                               'minutes': minutes,
                               'hours': hours,
                               'days': days}
        
        return granularity_details


    def get_reduced_granularity(self, granularity_details, fraction):
        '''Returns a candlestick granularity as a fraction of given granularity'''
        secs = granularity_details['seconds']
        mins = granularity_details['minutes']
        hrs  = granularity_details['hours']
        days = granularity_details['days']
        
        total_seconds = secs + 60*mins + 60*60*hrs + 60*60*24*days
        
        fractional_seconds = total_seconds/fraction
        
        seconds = fractional_seconds
        minutes = fractional_seconds/60
        hours = fractional_seconds/(60*60)
        days = fractional_seconds/(60*60*24)
        
        if days > 1:
            letter = 'D'
            number = 1
            reduced_granularity = letter
            
        elif hours > 1:
            base   = 2
            letter = 'H'
            number = base*round(hours/base)
            if number > 12:
                number = 12
            reduced_granularity = letter + str(number)
                
        elif minutes > 1:
            base   = 15 
            letter = 'M'
            number = base*round(minutes/base)
            if number > 30:
                number = 30
            reduced_granularity = letter + str(number)
            
        else: 
            base   = 15 
            letter = 'S'
            number = base*round(seconds/base)
            if number > 30:
                number = 30
            reduced_granularity = letter + str(number)
        
        if reduced_granularity[1:] == '0':
            reduced_granularity = reduced_granularity[0] + '1'
        
        return reduced_granularity
    
    
    def get_pip_location(self, instrument: str):
        """Returns the pip location of the requested instrument.
        """
        response = self.api.account.instruments(self.ACCOUNT_ID, 
                                                instruments=instrument)
        return response.body['instruments'][0].pipLocation
    
    
    def get_trade_unit_precision(self, instrument: str):
        """Returns the trade unit precision for the requested instrument.
        """
        # TODO - implement checking using this method
        response = self.api.account.instruments(self.ACCOUNT_ID, 
                                                instruments=instrument)
        return response.body['instruments'][0].tradeUnitsPrecision
    
    
    def _check_connection(self) -> None:
        """Connects to Oanda v20 REST API. An initial call is performed to check
        for a timeout error.
        """
        # TODO - improve this - currently doubles the poll rate
        for atempt in range(10):
            try:
                # Attempt basic task to check connection
                self.api.account.get(accountID=self.ACCOUNT_ID)
            
            except BaseException as ex:
                # Error has occurred
                ex_type, ex_value, ex_traceback = sys.exc_info()
            
                # Extract unformatter stack traces as tuples
                trace_back = traceback.extract_tb(ex_traceback)
            
                # Format stacktrace
                stack_trace = list()
            
                for trace in trace_back:
                    trade_string = "File : %s , Line : %d, " % (trace[0], trace[1]) + \
                                   "Func.Name : %s, Message : %s" % (trace[2], trace[3])
                    stack_trace.append(trade_string)
                
                print("\nWARNING FROM OANDA API: The following exception was caught.")
                print("Time: {}".format(datetime.datetime.now().strftime("%b %d %H:%M:%S")))
                print("Exception type : %s " % ex_type.__name__)
                print("Exception message : %s" %ex_value)
                print("Stack trace : %s" %stack_trace)
                print("  Attempting to reconnect to Oanda v20 API.")
                
                time.sleep(3)
                api = v20.Context(hostname = self.API, 
                                  token = self.ACCESS_TOKEN, 
                                  port = self.port)
                self.api = api
            
            else:
                break
            
        else:
            print("FATAL: All attempts to connect to Oanda API have failed.")
        
        
    def _get_price(self, instrument: str, **kwargs) -> dict:
        """Returns current price (bid+ask) and home conversion factors.
        """
        self._check_connection()
        response = self.api.pricing.get(accountID = self.ACCOUNT_ID, 
                                   instruments = instrument)
        ask = response.body["prices"][0].closeoutAsk
        bid = response.body["prices"][0].closeoutBid
        negativeHCF = response.body["prices"][0].quoteHomeConversionFactors.negativeUnits
        positiveHCF = response.body["prices"][0].quoteHomeConversionFactors.positiveUnits
    
        price = {"ask": ask,
                 "bid": bid,
                 "negativeHCF": negativeHCF,
                 "positiveHCF": positiveHCF
                 }
    
        return price
    
    
    def _place_market_order(self, order: Order):
        """Places market order.
        """
        self._check_connection()
        stop_loss_details = self._get_stop_loss_details(order)
        take_profit_details = self._get_take_profit_details(order)
        
        # Check position size
        size = self.check_trade_size(order.instrument, 
                                     order.size)
        
        response = self.api.order.market(accountID = self.ACCOUNT_ID,
                                         instrument = order.instrument,
                                         units = size,
                                         takeProfitOnFill = take_profit_details,
                                         stopLossOnFill = stop_loss_details,)
        return response
    
    
    def _place_stop_limit_order(self, order):
        """Places MarketIfTouchedOrder with Oanda.
        https://developer.oanda.com/rest-live-v20/order-df/
        """
        self._check_connection()
        
        stop_loss_details = self._get_stop_loss_details(order)
        take_profit_details = self._get_take_profit_details(order)
        
        # Check and correct order stop price
        price = self._check_precision(order.instrument, 
                                     order.order_stop_price)
        
        trigger_condition = order.trigger_price if "trigger_price" in order else "DEFAULT"
        
        # Need to test cases when no stop/take is provided (as None type)
        response = self.api.order.market_if_touched(accountID = self.ACCOUNT_ID,
                                                    instrument = order.instrument,
                                                    units = order.size,
                                                    price = str(price),
                                                    takeProfitOnFill = take_profit_details,
                                                    stopLossOnFill = stop_loss_details,
                                                    triggerCondition = trigger_condition)
        return response
    
    
    def _place_limit_order(self, order: Order):
        """(NOT YET IMPLEMENTED) PLaces limit order. 
        """
        raise Exception("Limit orders are not yet implemented for Oanda. "+\
                        "Please raise an issue on GitHub.")
        

    def _get_stop_loss_details(self, order: Order) -> dict:
        """Constructs stop loss details dictionary.
        """
        self._check_connection()
        if order.stop_type is not None:
            price = self._check_precision(order.instrument, order.stop_loss)
            
            if order.stop_type == 'trailing':
                # Trailing stop loss order
                stop_loss_details = {"price": str(price),
                                     "type": "TRAILING_STOP_LOSS"}
            else:
                stop_loss_details = {"price": str(price)}
        else:
            stop_loss_details = None
        
        return stop_loss_details
    
    
    def _get_take_profit_details(self, order: Order) -> dict:
        """Constructs take profit details dictionary.
        """
        self._check_connection()
        if order.take_profit is not None:
            price = self._check_precision(order.instrument, order.take_profit)
            take_profit_details = {"price": str(price)}
        else:
            take_profit_details = None
        
        return take_profit_details


    def _check_response(self, response):
        """Checks API response (currently only for placing orders).
        """
        if response.status != 201:
            message = response.body['errorMessage']
        else:
            message = "Success."
            
        output = {'Status': response.status, 
                  'Message': message}
        # TODO - print errors
        return output
    
    
    def _close_position(self, instrument, long_units=None, short_units=None,
                       **kwargs):
        """Closes all open positions on an instrument.
        """
        self._check_connection()
        # Check if the position is long or short
        # Temp code to close all positions
        # Close all long units
        response = self.api.position.close(accountID=self.ACCOUNT_ID, 
                                           instrument=instrument,
                                           longUnits="ALL")
        
        # Close all short units
        response = self.api.position.close(accountID=self.ACCOUNT_ID, 
                                           instrument=instrument,
                                           shortUnits="ALL")
        
        # TODO - the code below makes no sense currently; specifically, 
        # position.long.Units ????

        # open_position = self.get_open_positions(instrument)        

        # if len(open_position) > 0:
        #     position = open_position['position']
            
        #     if long_units is None:
        #         long_units  = position.long.units
        #     if short_units is None:
        #         short_units = position.short.units
            
        #     if long_units > 0:
        #         response = self.api.position.close(accountID=self.ACCOUNT_ID, 
        #                                            instrument=instrument, 
        #                                            longUnits="ALL")
            
        #     elif short_units > 0: 
        #         response = self.api.position.close(accountID=self.ACCOUNT_ID, 
        #                                            instrument=instrument,
        #                                            shortUnits="ALL")
            
        #     else:
        #         print("There is no current position with {} to close.".format(instrument))
        #         response = None
        # else:
        #     response = None
            
        return response
    
    
    def _get_precision(self, instrument: str):
        """Returns the allowable precision for a given pair.
        """
        self._check_connection()
        response = self.api.account.instruments(accountID = self.ACCOUNT_ID, 
                                                instruments = instrument)
        precision = response.body['instruments'][0].displayPrecision
        return precision

    
    def _check_precision(self, instrument, price):
        """Modify a price based on required ordering precision for pair.
        """
        N = self._get_precision(instrument)
        corrected_price = round(price, N)
        return corrected_price
    
    
    def _get_order_book(self, instrument: str):
        """Returns the order book of the instrument specified. 
        """
        response = self.api.instrument.order_book(instrument)
        return response.body['orderBook']
        
    
    def _get_position_book(self, instrument: str):
        """Returns the position book of the instrument specified. 
        """
        response = self.api.instrument.position_book(instrument)
        return response.body['positionBook']
    
    
    