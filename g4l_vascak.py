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

    # TODO

    all_lab_links = {
        # url: name
    }

    lab_tasks = []

    session = requests.Session()

    for category_url in all_category_urls:
        text = VASCAK.cached_session.get(category_url).text
        soup = BeautifulSoup(text, 'lxml')
        for div_element in soup.find_all(class_='exptPadng'):
            for a_element in div_element.find_all('a'):
                inner_text = a_element.get_text().strip()
                if inner_text:
                    all_lab_links[a_element['href']] = inner_text
                    lab_tasks.append(ObtainVascakLabDataTask(a_element['href'], session))
    
    run_tasks(lab_tasks)
    
    result = {
        'laboratories' : [],
        'all_links': [],
    }
    all_labs = []
    for task in lab_tasks:
        if task.result:
            name = all_lab_links[task.laboratory_id]
            iframe_url = task.result['url'] 
            sim_url = task.result['sim_url']
            
            lab = Laboratory(name=name, laboratory_id=iframe_url, description=name, home_url=sim_url)
            result['laboratories'].append(lab)
            result['all_links'].append({
                'lab': lab,
                'name': name,
                'base-url': task.laboratory_id,
                'sim-url': sim_url,
                'iframe-url': iframe_url,
            })

    VASCAK.rlms_cache['get_laboratories'] = result
    return result


FORM_CREATOR = VascakFormCreator()

CAPABILITIES = [ Capabilities.WIDGET, Capabilities.URL_FINDER ]

class RLMS(BaseRLMS):

    def __init__(self, configuration, *args, **kwargs):
        self.configuration = json.loads(configuration or '{}')

    def get_version(self):
        return Versions.VERSION_1

    def get_capabilities(self):
        return CAPABILITIES 

    def get_laboratories(self, **kwargs):
        return get_laboratories()['laboratories']

    def get_base_urls(self):
        return [ 'http://www.vascak.cz' ]

    def get_lab_by_url(self, url):
        laboratories = get_laboratories()
        # check the s=<IDENTIFIER> and that's it
        for lab in laboratories['all_links']:
            if False: # TODO
                return lab['lab']
        return None

    def reserve(self, laboratory_id, username, institution, general_configuration_str, particular_configurations, request_payload, user_properties, *args, **kwargs):
        response = {
            'reservation_id' : laboratory_id,
            'load_url' : laboratory_id
        }
        return response

    def load_widget(self, reservation_id, widget_name, **kwargs):
        return {
            'url' : reservation_id
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

@vascak_blueprint.route('/flash/<vascak_id>/')
def flash(vascak_id):
    return """<html>
    <body>
		<object classid="clsid:d27cdb6e-ae6d-11cf-96b8-444553540000" codebase="http://download.macromedia.com/pub/shockwave/cabs/flash/swflash.cab#version=10,0,0,0" width="478" height="765">
		  <param name=movie value="http://www.vascak.cz/data/android/physicsatschool/{IDENTIFIER}.swf?language=es">
		  <param name=quality value=high> 
		  <param name=bgcolor value="#ffffff">
		  <param name="wmode" value="transparent">   
		  <embed src="http://www.vascak.cz/data/android/physicsatschool/{IDENTIFIER}.swf?language=es" quality=high wmode="transparent" bgcolor="#ffffff" width="478" height="765" type="application/x-shockwave-flash" pluginspage="http://www.macromedia.com/go/getflashplayer"></embed> 
		</object>
    </body>
    </html>""".format(vascak_id)

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
