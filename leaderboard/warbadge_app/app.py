#!/usr/bin/env python
from __future__ import print_function  # In python 2.7
import json
import operator

from flask import Flask, render_template, request, abort
from flask.ext.cache import Cache
from flaskext.mysql import MySQL
from netaddr import EUI, mac_unix

#  Setup the Flask application
mysql = MySQL()
app = Flask(__name__)
app.config.from_object(__name__)
app.config['MYSQL_DATABASE_USER'] = 'put user here'
app.config['MYSQL_DATABASE_PASSWORD'] = 'put password here'
app.config['MYSQL_DATABASE_DB'] = 'put db name here'
app.config['MYSQL_DATABASE_HOST'] = 'put host here'
mysql.init_app(app)
""" Caching for API/HTTP routes. Simple is the built in
    caching mechanism for this module. It also supports
    things like Redis, memcache etc.. """
cache = Cache(app, config={'CACHE_TYPE': 'simple'})


#  Staff handles will be displayed as STAFF in the leaderboard.
STAFF = ['btm', 'Terry', 'effffn', 'ipl31', 'sandinak']


def log(msg):
    app.log(msg)


def bad_ssid(ssid):
    # if re.match('8====', ssid):
    #     return True
    return False


def get_handle_for_mac(mac):
    query = "SELECT * FROM handles WHERE `badge_mac`='{0}'".format(mac)
    conn = mysql.connect()
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    try:
        result = data[0][2]
    except IndexError:
        # log("Index error, wrong mac or missing handle?")
        result = "--------"
    return result


def get_top_ssids():
    query = ("SELECT ssid, COUNT(ssid) AS popularity FROM entries"
             " GROUP BY ssid ORDER BY popularity DESC limit 20")
    conn = mysql.connect()
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    return data


def get_top_bssids():
    query = ("SELECT bssid_mac, COUNT(bssid_mac) AS popularity "
             "FROM entries GROUP BY bssid_mac "
             "ORDER BY popularity DESC limit 20")
    conn = mysql.connect()
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    return data


def get_total_entries():
    query = " select COUNT(*) from entries"
    conn = mysql.connect()
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchone()
    conn.close()
    return data


def get_unique_checkins():
    """ Get all unique badge and bssid combos """
    query = ("SELECT badge_mac, bssid_mac FROM "
             "(SELECT DISTINCT badge_mac, bssid_mac FROM entries) "
             "AS internalQuery")
    conn = mysql.connect()
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    return data


def get_scoreboard_data():
    count = []
    data = get_unique_checkins()
    handles = {}
    for d in data:
        if d[0] not in handles.keys():
            handle = get_handle_for_mac(d[0])
            handle = handle.strip()
            if handle in STAFF:
                handle = "{0} *STAFF".format(handle)
            handles[d[0]] = handle
        else:
            pass
        if any(d[0] in x for x in count):
            continue
        result = [d[0], sum(x.count(d[0]) for x in data), handles[d[0]]]
        count.append(result)
    tally = {}
    for e in count:
        mac = EUI(e[0])
        mac.dialect = mac_unix
        tally[str(mac)] = [e[1], e[2]]
    sorted_tally = sorted(tally.items(), key=operator.itemgetter(1))
    return list(reversed(sorted_tally))


@app.route("/")
@cache.cached(timeout=50)
def main():
    return render_template('index.html')


@app.route("/stats")
@cache.cached(timeout=60)
def stats():
    bssids = get_top_bssids()
    ssids = get_top_ssids()
    total = get_total_entries()
    return render_template('stats.html', bssids=bssids,
                           ssids=ssids, total=total)


@app.route("/scoreboard")
@cache.cached(timeout=60)
def scorev2():
    scores = get_scoreboard_data()
    leader = scores[0][1][1]
    return render_template('scoresv2.html', leader=leader, scores=scores)


@app.route('/handles/')
def handles():
    query = "SELECT * FROM handles"
    conn = mysql.connect()
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    results = []
    for d in data:
        results.append(d)
    return json.dumps(data)


@app.route('/handle_for_mac/<mac>', methods=['GET'])
def handle_for_mac(mac):
    handle = get_handle_for_mac(mac)
    return json.dumps(handle)


@app.route('/handle/<mac>', methods=['POST'])
def handle(mac):
    log("update handle for %s" % mac)
    data = request.get_json()
    handle = data['handle']
    insert_template = ("INSERT INTO handles (badge_mac, handle) "
                       "VALUES('{0}', '{1}')".format(mac, handle))
    conn = mysql.connect()
    cursor = conn.cursor()
    try:
        cursor.execute(insert_template)
        conn.commit()
        log("Finished a transaction")
        return_code = 201
    except MySQLdb.IntegrityError as e:
        if e[0] == 1062:
            return_code = 409
        else:
            log("MySQL ERROR: %s" % e)
            return_code = 500
    finally:
        conn.close()
    payload = json.dumps({'warbadging': True}),
    content_type = {'ContentType': 'application/json'}
    return payload, return_code, content_type


@app.route("/checkin/<mac>", methods=['POST'])
def checkin(mac):
    ua = request.headers.get('User-Agent')
    if "WarBadge Experimental ShmooCon 2018" not in ua:
        log("Bad UA: %s" % ua)
        abort(403)
    insert_template = (u"INSERT INTO entries "
                       "(badge_mac, ssid, bssid_mac, rssi) "
                       "VALUES('{0}', '{1}', '{2}', {3})")

    conn = mysql.connect()
    cursor = conn.cursor()

    badge_mac = mac
    try:
        data = request.get_json()
        for ssid, entries in data.iteritems():
            if bad_ssid(ssid):
                raise NameError(ssid)
            for bssid_mac, rssi in entries.iteritems():
                insert = insert_template.format(badge_mac,
                                                conn.escape_string(ssid),
                                                bssid_mac, rssi)
                cursor.execute(insert)
                conn.commit()
                return_code = 201
    except NameError as e:
        log("Bad SSID: %s" % e)
        return_code = 403
    except Exception as e:
        log("Caught Exception (unicode?) for %s: %s" % (mac, e))
        log(request.data)
        return_code = 500
    else:
        log("Successful checkin for %s" % mac)
    finally:
        conn.close()
    payload = json.dumps({'warbadging': True}),
    content_type = {'ContentType': 'application/json'}
    return payload, return_code, content_type


@app.route("/checkin_old/<mac>", methods=['POST'])
def checkin_old(mac):
    # TODO: check user agent
    # Sanitize input to mysql query
    badge_mac = mac
    data = request.get_json()
    ssid = data['ssid']
    bssid_mac = data['bssid_mac']
    rssi = data['rssi']
    conn = mysql.connect()
    cursor = conn.cursor()
    insert = ("INSERT INTO entries (badge_mac, ssid, bssid_mac, rssi) "
              "VALUES('{0}', '{1}', '{2}', {3})"
              .format(badge_mac, ssid, bssid_mac, rssi))
    cursor.execute(insert)
    conn.commit()
    return_code = 201
    payload = json.dumps({'warbadging': True}),
    content_type = {'ContentType': 'application/json'}
    return payload, return_code, content_type


if __name__ == "__main__":
    app.run(host='127.0.0.1')
