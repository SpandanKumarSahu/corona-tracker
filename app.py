from __future__ import print_function
from flask import Flask, render_template, make_response
from flask import redirect, request, jsonify, url_for, send_file
import sys, os, json, pickle
import requests, urllib.parse
from GoogleNews import GoogleNews
from string import punctuation
from collections import Counter
from nltk import sent_tokenize
from newspaper import Article
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import spacy


# For server
app = Flask(__name__, template_folder = 'templates/')
app.secret_key = 's3cr3t'
app.debug = True
app._static_folder = os.path.abspath("templates/static/")

# For the Tracker
config = None
state = None
nlp = None
geolocator = None

def search():
    global state, config
    if config is None:
        raise Exception('Call initiateConfig first')
    if state is None:
        state = {}
    state['url'] = {}
    googlenews = GoogleNews()
    googlenews = GoogleNews('en','d')
    for city in config['cities']:
        googlenews.search('covid in '+city)
        state['url'][city] = []
        for i in range(config['pagesPerCity']):
            googlenews.getpage(i)
            state['url'][city].extend(googlenews.get__links())

def preprocess(txt):
    global config
    if config is None:
        raise Exception('Call initiateConfig first')
    # Break into words
    words = txt.split()
    # Remove words that are non-ASCII
    isascii = lambda s: len(s) == len(s.encode())
    words = [w for w in words if isascii(w)]
    # Remove words that are too long
    words = [w for w in words if len(w) <= config['maxWordLength']]
    return ' '.join(words)

def process1(txt, city):
    # String Matching
    words = txt.split()
    words = [w.translate({k:' ' for k in punctuation}).lower() for w in words]
    c = Counter(words)
    addr = open("data/address/"+city+".csv", "r").readlines()
    addr = [a.strip() for a in addr]
    locs = [w for w in c if (w in addr)]
    return locs

def process2(txt, city):
    nlp = spacy.load('en_core_web_sm')
    locs = []
    for sent in txt.split('.'):
        locs.extend([ent.text for ent in nlp(sent).ents if ent.label_ in config['accepted_labels']])
    return locs

def filter(locs, city):
    pass

def process(txt, city):
    # Preprocess
    txt = preprocess(txt)
    # String Matching
    locs = process1(txt, city)
    # NER
    locs.extend(process2(txt, city))
    # Filter using geotagging
    filter(locs, city)
    return locs

def geoloc(ls):
    global geolocator
    if geolocator is None:
        geolocator = Nominatim()
    ret = []
    for place in ls:
        location = geolocator.geocode(place)
        if location is not None:
            ret.append((location.latitude, location.longitude))
    return ret

def scrape():
    global state
    if config is None:
        raise Exception('Call initiateConfig first')
    if state is None:
        search()
    state['content'] = {}
    for city in config['cities']:
        state['content'][city] = []
        for url in state['url'][city]:
            try:
                article = Article(url, language="en")
                article.download()
                article.parse()
                txt = article.text
            except:
                continue
            locs = process(txt, city)
            locs = [addr for addr in locs if addr != city]
            if len(locs) > 0:
                state['content'][city].append((locs, url))
                if 'final' not in state:
                    state['final'] = set()
                state['final'].update(geoloc(locs))

def save():
    global state
    pickle.dump(state, open("data/res/state.pkl", "wb"))

def restore():
    global state
    state = pickle.load(open("data/res/state.pkl", "rb"))

def initiateConfig():
    global config
    config = json.load(open("config.json", "r"))

def getClosestAddr(megaData, target):
    distList = [geodesic(loc, target).km for loc in megaData['locs']]
    return megaData['names'][distList.index(min(distList))]

@app.route('/', methods=['GET'])
def home():
    return render_template('layouts/index.html')

@app.route('/main', methods=['GET', 'POST'])
def main():
    try:
        global geolocator, config
        if config is None:
            initiateConfig()
        if geolocator is None:
            geolocator = Nominatim()
        megaData = pickle.load(open("data/res/Delhi.pkl", "rb"))
        coords = geolocator.geocode(request.form['user-loc'])
        message = None
        if coords is None or \
            geodesic([coords.latitude, coords.longitude], [28.7041, 77.1025]).km > 100.0:
            if coords is None:
                message = "Sorry! Can't resolve your location at the moment."
            else:
                message = "Sorry! We have data for Delhi NCR only."
            class Object(object):
                pass
            coords = Object()
            coords.latitude, coords.longitude = 28.7041, 77.1025
        data = {
            'locs': [[u, v] for u, v in list(zip(megaData['locs'], megaData['names']))],
            'setCords': [coords.latitude, coords.longitude],
            'addr': getClosestAddr(megaData, [coords.latitude, coords.longitude]),
        }
        if message is not None:
            data['message'] = message
        if data['addr'] in megaData['news']:
            data['news'] = megaData['news'][data['addr']][(-1) * config['maxNewsInTable']:]
            for i in range(len(data['news'])):
                data['news'][i][1] = data['news'][i][1].encode('ascii', 'ignore').decode('utf-8')
        return render_template('layouts/main.html', data = data)
    except:
        return home()

@app.route('/update', methods=['GET'])
def update():
    pswd = request.args.get('pswd')
    if pswd == secret_key:
        initiateConfig()
        search()
        scrape()
        save()
    return home()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
