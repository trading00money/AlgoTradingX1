//+------------------------------------------------------------------+
//|                                        GQ_ZMQ_Bridge.mq5        |
//|                              Gann-Ehlers Trading System          |
//|                              ZMQ Bridge EA — MT5 Edition         |
//|                                                                  |
//|  Uses raw libzmq.dll calls — no mql-zmq wrapper classes.         |
//|  Copy libzmq.dll (64-bit) into MQL5\Libraries\.                  |
//+------------------------------------------------------------------+
#property copyright "Gann-Ehlers Trading System"
#property version   "2.10"
#property description "ZeroMQ Bridge EA for MetaTrader 5 (raw DLL)"

//--- Raw ZMQ DLL imports
#import "libzmq.dll"
long   zmq_ctx_new();
int    zmq_ctx_term(long ctx);
long   zmq_socket(long ctx, int type);
int    zmq_close(long s);
int    zmq_bind(long s, const uchar &addr[]);
int    zmq_connect(long s, const uchar &addr[]);
int    zmq_unbind(long s, const uchar &addr[]);
int    zmq_send(long s, const uchar &buf[], ulong len, int flags);
int    zmq_recv(long s, uchar &buf[], ulong len, int flags);
int    zmq_setsockopt(long s, int optname, const uchar &optval[], ulong optvallen);
int    zmq_setsockopt_int(long s, int optname, int &optval, ulong optvallen);
int    zmq_errno();
#import

//--- Socket types
#define ZMQ_REP     4
#define ZMQ_PUB     1

//--- Socket options
#define ZMQ_SNDHWM  23
#define ZMQ_RCVHWM  24
#define ZMQ_RCVTIMEO 27

//--- Send/recv flags
#define ZMQ_DONTWAIT 1

//--- Inputs
input group  "=== ZMQ Ports ==="
input int    InpCommandPort  = 32768;
input int    InpDataPort     = 32769;
input int    InpHeartbeatSec = 5;

input group  "=== Trading ==="
input ulong  InpMagic        = 202400;
input string InpComment      = "GQ_BOT";
input uint   InpSlippage     = 5;

input group  "=== Streaming ==="
input bool   InpStreamTicks  = true;
input string InpSymbols      = "BTCUSD,XAUUSD,EURUSD,GBPUSD";

//--- Globals
long     g_ctx    = 0;
long     g_rep    = 0;
long     g_pub    = 0;
string   g_streamSymbols[];
datetime g_lastHB = 0;
bool     g_ok     = false;

//+------------------------------------------------------------------+
//| Helper: bind addr string → uchar[]                               |
//+------------------------------------------------------------------+
bool ZmqBind(long sock, string addr)
{
    uchar arr[];
    StringToCharArray(addr, arr, 0, StringLen(addr));
    ArrayResize(arr, ArraySize(arr) + 1);
    arr[ArraySize(arr) - 1] = 0;
    return zmq_bind(sock, arr) == 0;
}

bool ZmqUnbind(long sock, string addr)
{
    uchar arr[];
    StringToCharArray(addr, arr, 0, StringLen(addr));
    ArrayResize(arr, ArraySize(arr) + 1);
    arr[ArraySize(arr) - 1] = 0;
    return zmq_unbind(sock, arr) == 0;
}

//+------------------------------------------------------------------+
//| Helper: set integer socket option                                |
//+------------------------------------------------------------------+
bool ZmqSetOptInt(long sock, int opt, int val)
{
    uchar buf[4];
    buf[0] = (uchar)(val & 0xFF);
    buf[1] = (uchar)((val >> 8)  & 0xFF);
    buf[2] = (uchar)((val >> 16) & 0xFF);
    buf[3] = (uchar)((val >> 24) & 0xFF);
    return zmq_setsockopt(sock, opt, buf, 4) == 0;
}

//+------------------------------------------------------------------+
//| Helper: send string on socket (non-blocking option)              |
//+------------------------------------------------------------------+
bool ZmqSend(long sock, string text, bool nowait = false)
{
    uchar buf[];
    int len = StringLen(text);
    StringToCharArray(text, buf, 0, len);   // no null terminator
    return zmq_send(sock, buf, (ulong)len, nowait ? ZMQ_DONTWAIT : 0) >= 0;
}

//+------------------------------------------------------------------+
//| Helper: recv string (non-blocking)                               |
//+------------------------------------------------------------------+
string ZmqRecv(long sock, bool nowait = false)
{
    uchar buf[];
    ArrayResize(buf, 65536);
    int n = zmq_recv(sock, buf, (ulong)ArraySize(buf), nowait ? ZMQ_DONTWAIT : 0);
    if(n <= 0) return "";
    return CharArrayToString(buf, 0, n);
}

//+------------------------------------------------------------------+
int OnInit()
{
    g_ctx = zmq_ctx_new();
    if(g_ctx == 0) { Print("FAILED zmq_ctx_new"); return INIT_FAILED; }

    g_rep = zmq_socket(g_ctx, ZMQ_REP);
    g_pub = zmq_socket(g_ctx, ZMQ_PUB);
    if(g_rep == 0 || g_pub == 0) { Print("FAILED zmq_socket"); return INIT_FAILED; }

    // Non-blocking receive: return immediately if no message
    ZmqSetOptInt(g_rep, ZMQ_RCVTIMEO, 0);
    ZmqSetOptInt(g_rep, ZMQ_SNDHWM,   1000);
    ZmqSetOptInt(g_rep, ZMQ_RCVHWM,   1000);
    ZmqSetOptInt(g_pub, ZMQ_SNDHWM,   10000);

    string repAddr = "tcp://*:" + IntegerToString(InpCommandPort);
    string pubAddr = "tcp://*:" + IntegerToString(InpDataPort);

    if(!ZmqBind(g_rep, repAddr)) { Print("FAILED bind REP errno=", zmq_errno()); return INIT_FAILED; }
    if(!ZmqBind(g_pub, pubAddr)) { Print("FAILED bind PUB errno=", zmq_errno()); return INIT_FAILED; }

    Print("GQ Bridge ready — REP:", InpCommandPort, "  PUB:", InpDataPort);
    Print("Account: ", AccountInfoInteger(ACCOUNT_LOGIN),
          "  Balance: ", AccountInfoDouble(ACCOUNT_BALANCE));

    ParseSymbols(InpSymbols);
    g_lastHB = TimeCurrent();
    g_ok     = true;
    EventSetMillisecondTimer(200);   // poll commands even when no ticks
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnTimer()
{
    if(!g_ok) return;
    PollCommands();
    if(TimeCurrent() - g_lastHB >= InpHeartbeatSec) { g_lastHB = TimeCurrent(); PublishHeartbeat(); }
}

void OnDeinit(const int reason)
{
    EventKillTimer();
    g_ok = false;
    if(g_rep != 0) { ZmqUnbind(g_rep, "tcp://*:" + IntegerToString(InpCommandPort)); zmq_close(g_rep); g_rep = 0; }
    if(g_pub != 0) { ZmqUnbind(g_pub, "tcp://*:" + IntegerToString(InpDataPort));    zmq_close(g_pub); g_pub = 0; }
    if(g_ctx != 0) { zmq_ctx_term(g_ctx); g_ctx = 0; }
    Print("GQ Bridge stopped. reason=", reason);
}

//+------------------------------------------------------------------+
void OnTick()
{
    if(!g_ok) return;
    PollCommands();
    if(InpStreamTicks) PublishTicks();
    if(TimeCurrent() - g_lastHB >= InpHeartbeatSec) { g_lastHB = TimeCurrent(); PublishHeartbeat(); }
}

//+------------------------------------------------------------------+
void PollCommands()
{
    string cmd = ZmqRecv(g_rep, true);   // non-blocking
    if(StringLen(cmd) == 0) return;

    string action = JsonGet(cmd, "action");
    string reply  = Dispatch(cmd, action);
    ZmqSend(g_rep, reply);
}

//+------------------------------------------------------------------+
string Dispatch(string cmd, string action)
{
    if(action == "PING")          return Pong();
    if(action == "GET_ACCOUNT")   return GetAccount();
    if(action == "GET_PRICE")     return GetPrice(JsonGet(cmd, "symbol"));
    if(action == "GET_HISTORY")   return GetHistory(JsonGet(cmd, "symbol"), JsonGet(cmd, "timeframe"), (int)StringToInteger(JsonGet(cmd, "bars")), StringToInteger(JsonGet(cmd, "from_time")), StringToInteger(JsonGet(cmd, "to_time")));
    if(action == "GET_POSITIONS") return GetPositions();
    if(action == "PLACE_ORDER")   return PlaceOrder(cmd);
    if(action == "MODIFY_ORDER")  return ModifyOrder(cmd);
    if(action == "CLOSE_ORDER")   return CloseOrder(cmd);
    return "{\"status\":\"ERROR\",\"message\":\"Unknown action: " + action + "\"}";
}

//+------------------------------------------------------------------+
string Pong()
{
    return "{\"status\":\"OK\",\"action\":\"PONG\",\"timestamp\":" + IntegerToString(TimeCurrent()) + "}";
}

//+------------------------------------------------------------------+
string GetAccount()
{
    string j = "{";
    j += "\"status\":\"OK\",";
    j += "\"login\":"        + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))          + ",";
    j += "\"name\":\""       + AccountInfoString(ACCOUNT_NAME)                             + "\",";
    j += "\"server\":\""     + AccountInfoString(ACCOUNT_SERVER)                           + "\",";
    j += "\"currency\":\""   + AccountInfoString(ACCOUNT_CURRENCY)                         + "\",";
    j += "\"balance\":"      + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),    2)    + ",";
    j += "\"equity\":"       + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),     2)    + ",";
    j += "\"margin\":"       + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN),     2)    + ",";
    j += "\"free_margin\":"  + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE),2)    + ",";
    j += "\"margin_level\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL),2)   + ",";
    j += "\"leverage\":"     + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE))       + ",";
    j += "\"profit\":"       + DoubleToString(AccountInfoDouble(ACCOUNT_PROFIT),     2);
    j += "}";
    return j;
}

//+------------------------------------------------------------------+
string GetPrice(string symbol)
{
    if(!SymbolSelect(symbol, true))
        return "{\"status\":\"ERROR\",\"message\":\"Symbol not found: " + symbol + "\"}";

    MqlTick tick;
    if(!SymbolInfoTick(symbol, tick))
        return "{\"status\":\"ERROR\",\"message\":\"No tick for " + symbol + "\"}";

    int d = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    string j = "{";
    j += "\"status\":\"OK\",";
    j += "\"symbol\":\""  + symbol                    + "\",";
    j += "\"bid\":"       + DoubleToString(tick.bid,  d) + ",";
    j += "\"ask\":"       + DoubleToString(tick.ask,  d) + ",";
    j += "\"last\":"      + DoubleToString(tick.last, d) + ",";
    j += "\"time\":"      + IntegerToString(tick.time)   + ",";
    j += "\"volume\":"    + IntegerToString(tick.volume);
    j += "}";
    return j;
}

//+------------------------------------------------------------------+
string GetHistory(string symbol, string tf, int bars, long from_time=0, long to_time=0)
{
    if(bars <= 0) bars = 1000;
    if(bars > 50000) bars = 50000;
    if(!SymbolSelect(symbol, true))
        return "{\"status\":\"ERROR\",\"message\":\"Symbol not found: " + symbol + "\"}";

    ENUM_TIMEFRAMES period = TfToEnum(tf);
    MqlRates rates[];
    int n;
    if(from_time > 0 && to_time > 0)
        n = CopyRates(symbol, period, (datetime)from_time, (datetime)to_time, rates);
    else
        n = CopyRates(symbol, period, 0, bars, rates);
    if(n <= 0)
        return "{\"status\":\"ERROR\",\"message\":\"No data for " + symbol + " " + tf + "\"}";

    int d = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    string j = "{\"status\":\"OK\",\"symbol\":\"" + symbol + "\",\"timeframe\":\"" + tf + "\",\"data\":[";

    for(int i = 0; i < n; i++)
    {
        if(i > 0) j += ",";
        double price_open  = rates[i].open;
        double price_high  = rates[i].high;
        double price_low   = rates[i].low;
        double price_close = rates[i].close;
        long   vol         = rates[i].tick_volume;
        j += "{";
        j += "\"time\":"   + IntegerToString(rates[i].time) + ",";
        j += "\"open\":"   + DoubleToString(price_open,  d) + ",";
        j += "\"high\":"   + DoubleToString(price_high,  d) + ",";
        j += "\"low\":"    + DoubleToString(price_low,   d) + ",";
        j += "\"close\":"  + DoubleToString(price_close, d) + ",";
        j += "\"volume\":" + IntegerToString(vol);
        j += "}";
    }
    j += "]}";
    return j;
}

//+------------------------------------------------------------------+
string GetPositions()
{
    string j = "{\"status\":\"OK\",\"positions\":[";
    int total = PositionsTotal();
    for(int i = 0; i < total; i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0) continue;
        string sym = PositionGetString(POSITION_SYMBOL);
        int d = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
        if(i > 0) j += ",";
        j += "{";
        j += "\"ticket\":"        + IntegerToString(ticket)                                         + ",";
        j += "\"symbol\":\""      + sym                                                             + "\",";
        j += "\"type\":"          + IntegerToString((int)PositionGetInteger(POSITION_TYPE))         + ",";
        j += "\"volume\":"        + DoubleToString(PositionGetDouble(POSITION_VOLUME),       2)     + ",";
        j += "\"open_price\":"    + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN),   d)     + ",";
        j += "\"current_price\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT),d)     + ",";
        j += "\"sl\":"            + DoubleToString(PositionGetDouble(POSITION_SL),           d)     + ",";
        j += "\"tp\":"            + DoubleToString(PositionGetDouble(POSITION_TP),           d)     + ",";
        j += "\"profit\":"        + DoubleToString(PositionGetDouble(POSITION_PROFIT),       2)     + ",";
        j += "\"swap\":"          + DoubleToString(PositionGetDouble(POSITION_SWAP),         2)     + ",";
        j += "\"magic\":"         + IntegerToString(PositionGetInteger(POSITION_MAGIC))             + ",";
        j += "\"open_time\":"     + IntegerToString(PositionGetInteger(POSITION_TIME));
        j += "}";
    }
    j += "]}";
    return j;
}

//+------------------------------------------------------------------+
string PlaceOrder(string cmd)
{
    string symbol  = JsonGet(cmd, "symbol");
    string side    = JsonGet(cmd, "side");
    double volume  = StringToDouble(JsonGet(cmd, "volume"));
    double sl      = StringToDouble(JsonGet(cmd, "stop_loss"));
    double tp      = StringToDouble(JsonGet(cmd, "take_profit"));
    ulong  magic   = (ulong)StringToInteger(JsonGet(cmd, "magic"));
    string comment = JsonGet(cmd, "comment");

    if(volume <= 0)   volume  = 0.01;
    if(magic  == 0)   magic   = InpMagic;
    if(comment == "") comment = InpComment;

    if(!SymbolSelect(symbol, true))
        return "{\"status\":\"ERROR\",\"message\":\"Symbol not found: " + symbol + "\"}";

    MqlTick tick;
    SymbolInfoTick(symbol, tick);

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action       = TRADE_ACTION_DEAL;
    req.symbol       = symbol;
    req.volume       = volume;
    req.type         = (side == "long") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    req.price        = (side == "long") ? tick.ask : tick.bid;
    req.sl           = sl;
    req.tp           = tp;
    req.deviation    = InpSlippage;
    req.magic        = magic;
    req.comment      = comment;
    req.type_filling = ORDER_FILLING_IOC;

    if(!OrderSend(req, res))
        return "{\"status\":\"ERROR\",\"message\":\"" + res.comment + "\",\"retcode\":" + IntegerToString(res.retcode) + "}";

    int d = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    string j = "{";
    j += "\"status\":\"OK\",";
    j += "\"ticket\":"   + IntegerToString(res.order)    + ",";
    j += "\"symbol\":\"" + symbol                        + "\",";
    j += "\"side\":\""   + side                          + "\",";
    j += "\"volume\":"   + DoubleToString(res.volume, 2) + ",";
    j += "\"price\":"    + DoubleToString(res.price,  d);
    j += "}";
    return j;
}

//+------------------------------------------------------------------+
string ModifyOrder(string cmd)
{
    ulong  ticket = (ulong)StringToInteger(JsonGet(cmd, "ticket"));
    double sl     = StringToDouble(JsonGet(cmd, "stop_loss"));
    double tp     = StringToDouble(JsonGet(cmd, "take_profit"));

    if(!PositionSelectByTicket(ticket))
        return "{\"status\":\"ERROR\",\"message\":\"Position not found\"}";

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action   = TRADE_ACTION_SLTP;
    req.symbol   = PositionGetString(POSITION_SYMBOL);
    req.position = ticket;
    req.sl       = sl;
    req.tp       = tp;

    if(!OrderSend(req, res))
        return "{\"status\":\"ERROR\",\"message\":\"" + res.comment + "\",\"retcode\":" + IntegerToString(res.retcode) + "}";

    return "{\"status\":\"OK\",\"ticket\":" + IntegerToString(ticket) + "}";
}

//+------------------------------------------------------------------+
string CloseOrder(string cmd)
{
    ulong  ticket = (ulong)StringToInteger(JsonGet(cmd, "ticket"));
    double volume = StringToDouble(JsonGet(cmd, "volume"));

    if(!PositionSelectByTicket(ticket))
        return "{\"status\":\"ERROR\",\"message\":\"Position not found\"}";

    string symbol = PositionGetString(POSITION_SYMBOL);
    double lots   = (volume > 0) ? volume : PositionGetDouble(POSITION_VOLUME);

    MqlTick tick;
    SymbolInfoTick(symbol, tick);

    MqlTradeRequest req = {};
    MqlTradeResult  res = {};
    req.action       = TRADE_ACTION_DEAL;
    req.symbol       = symbol;
    req.position     = ticket;
    req.volume       = lots;
    req.type         = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
    req.price        = (req.type == ORDER_TYPE_SELL) ? tick.bid : tick.ask;
    req.deviation    = InpSlippage;
    req.magic        = InpMagic;
    req.comment      = "Close " + InpComment;
    req.type_filling = ORDER_FILLING_IOC;

    if(!OrderSend(req, res))
        return "{\"status\":\"ERROR\",\"message\":\"" + res.comment + "\",\"retcode\":" + IntegerToString(res.retcode) + "}";

    int d = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    string j = "{";
    j += "\"status\":\"OK\",";
    j += "\"ticket\":"      + IntegerToString(ticket)        + ",";
    j += "\"close_price\":" + DoubleToString(res.price, d)   + ",";
    j += "\"volume\":"      + DoubleToString(res.volume, 2);
    j += "}";
    return j;
}

//+------------------------------------------------------------------+
void PublishTicks()
{
    for(int i = 0; i < ArraySize(g_streamSymbols); i++)
    {
        string sym = g_streamSymbols[i];
        MqlTick tick;
        if(!SymbolInfoTick(sym, tick)) continue;

        int d = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
        string msg = "{";
        msg += "\"type\":\"TICK\",";
        msg += "\"symbol\":\"" + sym                       + "\",";
        msg += "\"bid\":"      + DoubleToString(tick.bid,  d) + ",";
        msg += "\"ask\":"      + DoubleToString(tick.ask,  d) + ",";
        msg += "\"last\":"     + DoubleToString(tick.last, d) + ",";
        msg += "\"time\":"     + IntegerToString(tick.time)   + ",";
        msg += "\"volume\":"   + IntegerToString(tick.volume);
        msg += "}";
        ZmqSend(g_pub, msg);
    }
}

//+------------------------------------------------------------------+
void PublishHeartbeat()
{
    string msg = "{";
    msg += "\"type\":\"HEARTBEAT\",";
    msg += "\"time\":"      + IntegerToString(TimeCurrent())   + ",";
    msg += "\"positions\":" + IntegerToString(PositionsTotal());
    msg += "}";
    ZmqSend(g_pub, msg);
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &,
                        const MqlTradeResult      &)
{
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
    string snap = GetPositions();
    StringReplace(snap, "\"status\":\"OK\"", "\"type\":\"POSITION_UPDATE\"");
    ZmqSend(g_pub, snap);
}

//+------------------------------------------------------------------+
void ParseSymbols(string raw)
{
    string parts[];
    int n = StringSplit(raw, ',', parts);
    ArrayResize(g_streamSymbols, 0);
    for(int i = 0; i < n; i++)
    {
        string s = parts[i];
        StringTrimLeft(s);
        StringTrimRight(s);
        if(StringLen(s) == 0) continue;
        SymbolSelect(s, true);
        int idx = ArraySize(g_streamSymbols);
        ArrayResize(g_streamSymbols, idx + 1);
        g_streamSymbols[idx] = s;
    }
    Print("Streaming ", ArraySize(g_streamSymbols), " symbols");
}

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TfToEnum(string tf)
{
    if(tf == "M1")  return PERIOD_M1;
    if(tf == "M5")  return PERIOD_M5;
    if(tf == "M15") return PERIOD_M15;
    if(tf == "M30") return PERIOD_M30;
    if(tf == "H1")  return PERIOD_H1;
    if(tf == "H2")  return PERIOD_H2;
    if(tf == "H4")  return PERIOD_H4;
    if(tf == "D1")  return PERIOD_D1;
    if(tf == "W1")  return PERIOD_W1;
    if(tf == "MN1") return PERIOD_MN1;
    return PERIOD_H1;
}

//+------------------------------------------------------------------+
//| Minimal JSON key extractor (string values and numbers)            |
//+------------------------------------------------------------------+
string JsonGet(string json, string key)
{
    string searchKey = "\"" + key + "\"";
    int kp = StringFind(json, searchKey);
    if(kp < 0) return "";
    int colon = StringFind(json, ":", kp + StringLen(searchKey));
    if(colon < 0) return "";
    int s = colon + 1;
    while(s < StringLen(json))
    {
        ushort ch = StringGetCharacter(json, s);
        if(ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r') s++;
        else break;
    }
    ushort first = StringGetCharacter(json, s);
    if(first == '"')
    {
        int e = StringFind(json, "\"", s + 1);
        return (e > s) ? StringSubstr(json, s + 1, e - s - 1) : "";
    }
    int e = s;
    while(e < StringLen(json))
    {
        ushort ch = StringGetCharacter(json, e);
        if(ch == ',' || ch == '}' || ch == ']' || ch == ' ' || ch == '\n' || ch == '\r') break;
        e++;
    }
    return StringSubstr(json, s, e - s);
}
//+------------------------------------------------------------------+
