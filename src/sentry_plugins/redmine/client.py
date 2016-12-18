from __future__ import absolute_import

import logging

from requests import RequestException
from sentry import http
from sentry.exceptions import PluginError
from sentry.utils import json


class RedmineError(Exception):
    pass


class RedmineUnauthorized(RedmineError):
    pass


class RedmineClient(object):
    def __init__(self, host, key):
        host = host.rstrip('/')
        # Assume HTTP if no protocol specified
        if not host.startswith('http://') and not host.startswith('https://'):
            host = 'http://' + host
        self.host = host
        self.key = key

    def request(self, method, path, data=None):
        headers = {
            'X-Redmine-API-Key': self.key,
            'Content-Type': "application/json",
        }
        url = '{}{}'.format(self.host, path)
        session = http.build_session()

        try:
            req = getattr(session, method.lower())(url, json=data, headers=headers)
        except RequestException as e:
            resp = e.response
            if not resp:
                raise RedmineError('Internal Error')
            if resp.status_code == 401:
                raise RedmineUnauthorized(resp)
            raise RedmineError(resp)
        except Exception as e:
            logging.error('Error in request to %s: %s', url, e.message[:128],
                          exc_info=True)
            raise RedmineError('Internal error', 500)

        if req.status_code == 401:
            raise RedmineUnauthorized(req)
        elif req.status_code < 200 or req.status_code >= 300:
            raise RedmineError(req)

        if req.text:
            return json.loads(req.text)
        else:
            return {}

    def get_projects(self):
        return self.request('GET', '/projects.json')

    def get_trackers(self):
        return self.request('GET', '/trackers.json')

    def get_priorities(self):
        return self.request('GET', '/enumerations/issue_priorities.json')

    def get_issue(self, issue_id):
        return self.request('GET', '/issues/{}.json'.format(issue_id))

    def create_issue(self, data):
        response = self.request('POST', '/issues.json', data={
            'issue': data,
        })

        if 'issue' not in response or 'id' not in response['issue']:
            raise PluginError('Unable to create Redmine ticket')

        return response

    def add_comment(self, issue_id, comment):
        return self.request('PUT', '/issues/{}.json'.format(issue_id), data={
            'issue': {
                'notes': comment,
            }
        })
