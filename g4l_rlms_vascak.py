# -*-*- encoding: utf-8 -*-*-

import os
import re
import sys
import time
import sys
import urlparse
import json
import datetime
import uuid
import hashlib
import threading
import Queue
import functools
import traceback
import pprint

import requests
from bs4 import BeautifulSoup

from flask import Blueprint, request, url_for
from flask.ext.wtf import TextField, PasswordField, Required, URL, ValidationError

from labmanager.forms import AddForm
from labmanager.rlms import register, Laboratory, CacheDisabler, LabNotFoundError, register_blueprint
from labmanager.rlms.base import BaseRLMS, BaseFormCreator, Capabilities, Versions
from labmanager.rlms.queue import QueueTask, run_tasks

    
def dbg(msg):
    if DEBUG:
        print "[%s]" % time.asctime(), msg
        sys.stdout.flush()

def dbg_lowlevel(msg, scope):
    if DEBUG_LOW_LEVEL:
        print "[%s][%s][%s]" % (time.asctime(), threading.current_thread().name, scope), msg
        sys.stdout.flush()


class VascakAddForm(AddForm):

    DEFAULT_URL = 'http://www.vascak.cz'
    DEFAULT_LOCATION = 'Czech Republic'
    DEFAULT_PUBLICLY_AVAILABLE = True
    DEFAULT_PUBLIC_IDENTIFIER = 'vascak'
    DEFAULT_AUTOLOAD = True

    def __init__(self, add_or_edit, *args, **kwargs):
        super(VascakAddForm, self).__init__(*args, **kwargs)
        self.add_or_edit = add_or_edit

    @staticmethod
    def process_configuration(old_configuration, new_configuration):
        return new_configuration


class VascakFormCreator(BaseFormCreator):

    def get_add_form(self):
        return VascakAddForm

class ObtainVascakLabDataTask(QueueTask):
    def __init__(self, laboratory_id, session):
        self.session = session
        self.result = {}
        super(ObtainVascakLabDataTask, self).__init__(laboratory_id)

    def task(self):
        text = self.session.get(self.laboratory_id).text
        soup = BeautifulSoup(text, 'lxml')
        # TODO
        self.result = {
            'url' : base_url + '?' + args,
            'sim_url': simulator_link
        }

MIN_TIME = datetime.timedelta(hours=24)

def get_laboratories():
    laboratories = VASCAK.rlms_cache.get('get_laboratories',  min_time = MIN_TIME)
    if laboratories:
        return laboratories

    index = requests.get('http://www.vascak.cz/physicsanimations.php?l=en').text
    soup = BeautifulSoup(index, 'lxml')

    identifiers = set()
    for anchor_link in soup.find_all('a'):
        if anchor_link.get('href', '').startswith('data/android/physicsatschool/templateimg'):
            href = anchor_link['href']
            query = urlparse.urlparse(href).query
            params = dict(urlparse.parse_qsl(query))
            identifier = params.get('s')
            if identifier:
                identifiers.add(identifier)
        
    labs = []
    for identifier in identifiers:
        lab = Laboratory(name=identifier, laboratory_id=identifier, description=identifier)
        labs.append(lab)

    VASCAK.rlms_cache['get_laboratories'] = labs
    return labs


FORM_CREATOR = VascakFormCreator()

CAPABILITIES = [ Capabilities.WIDGET, Capabilities.URL_FINDER, Capabilities.TRANSLATION_LIST ]

class RLMS(BaseRLMS):

    def __init__(self, configuration, *args, **kwargs):
        self.configuration = json.loads(configuration or '{}')

    def get_version(self):
        return Versions.VERSION_1

    def get_capabilities(self):
        return CAPABILITIES 

    def get_laboratories(self, **kwargs):
        return get_laboratories()

    def get_base_urls(self):
        return [ 'http://www.vascak.cz' ]

    def get_lab_by_url(self, url):
        query = urlparse.urlparse(url).query
        params = dict(urlparse.parse_qsl(query))
        identifier = params.get('s')
        if not identifier:
            return None

        laboratories = get_laboratories()
        for lab in laboratories:
            if lab.laboratory_id == identifier:
                return lab

        return None

    def get_translation_list(self, laboratory_id):
        KEY = 'languages'
        languages = VASCAK.cache.get(KEY)
        if languages is None:
            languages = set([])
            index = requests.get('http://www.vascak.cz/physicsanimations.php?l=en').text
            soup = BeautifulSoup(index, 'lxml')
            for anchor in soup.find_all('a'):
                href = anchor.get('href') or ''
                query = urlparse.urlparse(href).query
                params = dict(urlparse.parse_qsl(query))
                language = params.get('language')
                if language:
                    languages.add(language)
               
            VASCAK.cache[KEY] = list(languages)

        return {
            'supported_languages' : languages
        }

    def reserve(self, laboratory_id, username, institution, general_configuration_str, particular_configurations, request_payload, user_properties, *args, **kwargs):
        locale = kwargs.get('locale', 'en')
        if '_' in locale:
            locale = locale.split('_')[0]

        url = create_url(laboratory_id, locale)        

        response = {
            'reservation_id' : laboratory_id,
            'load_url' : url,
        }
        return response

    def load_widget(self, reservation_id, widget_name, **kwargs):
        locale = kwargs.get('locale', 'en')
        if '_' in locale:
            locale = locale.split('_')[0]

        return {
            'url' : create_url(reservation_id, locale)
        }

    def list_widgets(self, laboratory_id, **kwargs):
        default_widget = dict( name = 'default', description = 'Default widget' )
        return [ default_widget ]


class VascakTaskQueue(QueueTask):
    RLMS_CLASS = RLMS

def populate_cache(rlms):
    rlms.get_laboratories()

VASCAK = register("Vascak", ['1.0'], __name__)
VASCAK.add_local_periodic_task('Populating cache', populate_cache, hours = 23)

DEBUG = VASCAK.is_debug() or (os.environ.get('G4L_DEBUG') or '').lower() == 'true' or False
DEBUG_LOW_LEVEL = DEBUG and (os.environ.get('G4L_DEBUG_LOW') or '').lower() == 'true'

if DEBUG:
    print("Debug activated")

if DEBUG_LOW_LEVEL:
    print("Debug low level activated")

vascak_blueprint = Blueprint('vascak', __name__)

def create_url(identifier, locale):
    return url_for('vascak.flash', vascak_id=identifier, lang=locale, _external=True)

@vascak_blueprint.route('/flash/<vascak_id>/')
def flash(vascak_id):
    language = request.args.get('lang') or 'en'
    return """<html>
    <body>
		<object classid="clsid:d27cdb6e-ae6d-11cf-96b8-444553540000" codebase="http://download.macromedia.com/pub/shockwave/cabs/flash/swflash.cab#version=10,0,0,0" width="100%" height="100%">
		  <param name=movie value="http://www.vascak.cz/data/android/physicsatschool/{identifier}.swf?language={language}">
		  <param name=quality value=high> 
		  <param name=bgcolor value="#ffffff">
		  <param name="wmode" value="transparent">   
		  <embed src="http://www.vascak.cz/data/android/physicsatschool/{identifier}.swf?language={language}" quality=high wmode="transparent" bgcolor="#ffffff" width="100%" height="100%" type="application/x-shockwave-flash" pluginspage="http://www.macromedia.com/go/getflashplayer"></embed> 
		</object>
    </body>
    </html>""".format(identifier=vascak_id, language=language)

register_blueprint(vascak_blueprint, url='vascak')

sys.stdout.flush()

def main():

    index = requests.get('http://www.vascak.cz/physicsanimations.php?l=en').text
    soup = BeautifulSoup(index, 'lxml')

    identifiers = set()
    for anchor_link in soup.find_all('a'):
        if anchor_link.get('href', '').startswith('data/android/physicsatschool/templateimg'):
            href = anchor_link['href']
            query = urlparse.urlparse(href).query
            params = dict(urlparse.parse_qsl(query))
            identifier = params.get('s')
            if identifier:
                identifiers.add(identifier)

    for identifier in identifiers:
        print identifier, 
        swf_file = [ line for line in requests.get('http://www.vascak.cz/data/android/physicsatschool/template.php?s={}&l=es&zoom=0'.format(identifier)).text.splitlines() if '<param name=movie' in line ][0].split('"')[1]
        if swf_file != '{}.swf?language=es'.format(identifier):
            print "*" * 20
            print swf_file
            print "*" * 20
        else:
            print "ok"

    return

    with CacheDisabler():
        rlms = RLMS("{}")
        t0 = time.time()
        laboratories = rlms.get_laboratories()
        tf = time.time()
        print len(laboratories), (tf - t0), "seconds"
        print
        print laboratories[:10]
        print
        # print rlms.reserve('http://phet.colorado.edu/en/simulation/beers-law-lab', 'tester', 'foo', '', '', '', '', locale = 'es_ALL')
    
        try:
            rlms.reserve('identifier-not-found', 'tester', 'foo', '', '', '', '', locale = 'xx_ALL')
        except LabNotFoundError:
            print "Captured error successfully"

        print rlms.get_base_urls()
        # print rlms.get_lab_by_url("https://phet.colorado.edu/en/simulation/acid-base-solutions")
    return

    for lab in laboratories[:5]:
        t0 = time.time()
        print rlms.reserve(lab.laboratory_id, 'tester', 'foo', '', '', '', '', locale = lang)
        tf = time.time()
        print tf - t0, "seconds"
    

if __name__ == '__main__':
    main()
