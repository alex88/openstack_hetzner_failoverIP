#!/opt/local/bin/python
import json
from httplib2 import Http
from urllib import urlencode
from urlparse import urlparse
from socket import gethostbyname
from time import sleep
import MySQLdb
import MySQLdb.cursors
import ConfigParser, os

#Insert the hetzner credentials for webservice
#TODO: put configuration in something like /etc/
hetzner_webservice_url = "https://robot-ws.your-server.de/"
hetzner_webservice_user = "youruser"
hetzner_webservice_password = "yourpass"

#Nova configuration path
nova_config_path = "/etc/nova/nova.conf"

#Arguments
verbose = True
resolve_nova_host = True
sleep_time = 30
#Recheck hetzner with api after #num nova checks
hetzner_recheck_count = 10

#Get configuration from nova config file
config = ConfigParser.ConfigParser()
config.readfp(open(nova_config_path))

mysql_config = urlparse(config.get('DEFAULT','sql_connection'))

#Set the mysql vars for connecting to the database
mysql_host = mysql_config.hostname
mysql_user = mysql_config.username
mysql_pass = mysql_config.password
mysql_db = mysql_config.path[1:None]

#Create the HTTP client for api requests and add credentials to be added on each request
h = Http()
h.add_credentials(hetzner_webservice_user, hetzner_webservice_password)
urlencodedHeaders = {'Content-type': 'application/x-www-form-urlencoded'}

#Variable to store hetzner ip and floating ip
ipList = {}

def getFailoverList():
	if verbose: print "Getting Hetzner failover ip list"
	resp, content = h.request(hetzner_webservice_url+"failover")
	tempList = json.loads(content)
	failoverList = {}
	for failoverIP in tempList:
		if verbose: print "Found failover %s routed to %s" % (failoverIP['failover']['ip'],failoverIP['failover']['active_server_ip'])
		failoverList[failoverIP['failover']['ip'].encode('ascii','ignore')] = failoverIP['failover']['active_server_ip'].encode('ascii','ignore')
	return failoverList

def moveFailover(failoverIP, destServerIP):
	data = {'active_server_ip':destServerIP}
	resp, content = h.request(hetzner_webservice_url+"failover/"+failoverIP, "POST", headers=urlencodedHeaders, body=urlencode(data))

def getNovaFloatingList():
	if verbose: print "Getting nova floating ip list"
	db = MySQLdb.connect(mysql_host,mysql_user,mysql_pass,mysql_db,cursorclass=MySQLdb.cursors.DictCursor)
	c = db.cursor()
	c.execute("SELECT * FROM floating_ips WHERE deleted = 0")
	rawdata = c.fetchall()
	floatingList = {}
	for row in rawdata:
		if verbose: print "Floating ip: %s assigned to %s" % (row['address'],row['host'])
		floatingList[row['address']] = translateHostToIP(row['host']) if resolve_nova_host and row['host'] else row['host']
	return floatingList

def translateHostToIP(hostname):
	return gethostbyname(hostname)

def initList(callHetznerApi = False):
	if(callHetznerApi):
		if verbose: print "Updating local ip list with Hetzner API"
		hetznerList = getFailoverList()
	else:
		if verbose: print "Updating local ip list with cached Hetzner results"
		hetznerList = {}
		for failoverIP, association in ipList.iteritems():
			hetznerList[failoverIP] = association['hetzner_host']
	floatingList = getNovaFloatingList()
	for failoverIP, hetzner_host in hetznerList.iteritems():
		ipList[failoverIP] = { 'hetzner_host': hetzner_host, 'nova_host': floatingList[failoverIP] if floatingList.has_key(failoverIP) and floatingList[failoverIP] is not None else None }
		if verbose: print "Failover Ip %s is routed to %s and associated in nova to %s" % (failoverIP,hetzner_host,floatingList[failoverIP] if floatingList.has_key(failoverIP) and floatingList[failoverIP] is not None else None)

def checkForChanges():
	if verbose: print "Checking for routing mismatch"

	for failoverIP, association in ipList.iteritems():
		if association['hetzner_host'] != association['nova_host'] and association['nova_host'] is not None:
			if verbose: print "Moving failover ip %s from %s to %s" % (failoverIP,association['hetzner_host'],association['nova_host'])
			moveFailover(failoverIP,association['nova_host'])
		else:
			if verbose: print "Ip %s is on %s nova has it associated to %s, no need to move" % (failoverIP,association['hetzner_host'],association['nova_host'])

loopCount = 0
initList(True)
while(True):
	if loopCount == hetzner_recheck_count:
		loopCount = 0
		initList(True)
	else:
		loopCount = loopCount + 1
		initList(False)
	checkForChanges()
	if verbose: print "Sleeping %d seconds..." % sleep_time
	sleep(sleep_time)