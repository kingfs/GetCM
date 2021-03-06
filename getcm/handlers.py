import tornado.web
import random
import urllib
import logging

from model.schema import File, Device
from getcm.utils.string import base62_encode
from tornado.web import asynchronous

class BaseHandler(tornado.web.RequestHandler):
    @property
    def activebuilds(self):
        return self.application.activebuilds

    @property
    def stats(self):
        return self.application.stats

    @property
    def db(self):
        return self.application.db

    @property
    def mirrorpool(self):
        return self.application.mirrorpool

    def render(self, template, params={}):
        tpl = self.application.lookup.get_template(template)
        self.write(tpl.render(**params))
        self.finish()

class BrowseHandler(BaseHandler):
    @asynchronous
    def get(self):
        device = self.request.arguments.get('device', [None])[0]
        type = self.request.arguments.get('type', [None])[0]
        files = File.browse(device, type)

        for fileobj in files:
            fileobj.base62 = base62_encode(fileobj.id)

        def respond(builds):
            return self.render("browse.mako", {'request_type': type, 'request_device': device, 'devices': Device.get_all(), 'files': files, 'builds': builds})

        self.stats.incr('view_browse')
        return self.activebuilds.get(respond)

class SumHandler(BaseHandler):
    def get(self, request):
        if request.endswith(".zip") and "/" not in request:
            fileobj = File.get_by_filename(request)
        elif request.endswith(".zip") and "/" in request:
            fileobj = File.get_by_fullpath(request)
        else:
            fileobj = File.get_by_base62(request)

        if fileobj is None:
            self.write("404 Not Found")
            return self.set_status(404)

        self.stats.incr('md5sum')
        return self.write("%s  %s" % (fileobj.filename, fileobj.md5sum))

class ZipHandler(BaseHandler):
    def get(self, request):
        request = request + ".zip"

        if "/" in request:
            fileobj = File.get_by_fullpath(request)
        elif "/" not in request:
            fileobj = File.get_by_filename(request)

        if fileobj is None and "/" not in request:
            self.write("404 Not Found")
            return self.set_status(404)
        elif fileobj is None:
            full_path = request
        else:
            full_path = fileobj.full_path
            self.stats.incr('bytes', fileobj.size)

        url = self.mirrorpool.next() % full_path

        webseed = self.request.arguments.get('webseed', [None])[0]
        if webseed:
            url = url + "?" + urllib.urlencode({'webseed': webseed})
            logging.warn("Webseeding for '%s'" % fileobj.filename)

        self.stats.incr('downloads')
        return self.redirect(url)

class Base62Handler(BaseHandler):
    def get(self, request):
        # Some torrent clients are retarded and urlencode the querystring.
        # if that happens, they don't deserve to download.
        if request.endswith("?webseed=1"):
            self.write("403 Forbidden")
            return self.set_status(403)

        fileobj = File.get_by_base62(request)
        if fileobj is None:
            self.write("404 Not Found")
            return self.set_status(404)

        url = self.mirrorpool.next() % fileobj.full_path

        webseed = self.request.arguments.get('webseed', [None])[0]
        if webseed:
            url = url + "?" + urllib.urlencode({'webseed': webseed})
            logging.warn("Webseeding for '%s'" % fileobj.filename)

        self.stats.incr('downloads')
        self.stats.incr('bytes', fileobj.size)
        return self.redirect(url)

class RssHandler(BaseHandler):
    def get(self):
        files = File.browse(None, None, 100)
        self.set_header('Content-Type', "application/xml; charset=utf-8")
        self.render("rss.mako", {'files': files})
