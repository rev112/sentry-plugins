from __future__ import absolute_import

import responses

from exam import fixture
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from sentry.testutils import PluginTestCase

from sentry_plugins.redmine.plugin import RedminePlugin


class RedminePluginTest(PluginTestCase):
    @fixture
    def plugin(self):
        return RedminePlugin()

    @fixture
    def request(self):
        return RequestFactory()

    def test_conf_key(self):
        assert self.plugin.conf_key == 'redmine'

    def test_entry_point(self):
        self.assertAppInstalled('redmine', 'sentry_plugins.redmine')
        self.assertPluginInstalled('redmine', self.plugin)

    def test_get_issue_label(self):
        group = self.create_group(message='Hello world', culprit='foo.bar')
        assert self.plugin.get_issue_label(group, 1) == 'Redmine-1'

    def test_get_issue_url(self):
        self.plugin.set_option('instance_url', 'http://localhost:3000', self.project)
        group = self.create_group(message='Hello world', culprit='foo.bar')
        assert self.plugin.get_issue_url(group, 1) == 'http://localhost:3000/issues/1'

    def test_is_configured(self):
        assert self.plugin.is_configured(None, self.project) is False
        self.plugin.set_option('instance_url', 'http://localhost:3000', self.project)
        self.plugin.set_option('key', '123', self.project)
        assert self.plugin.is_configured(None, self.project) is True

    @responses.activate
    def test_create_issue(self):
        responses.add(
            responses.POST,
            'http://localhost:3000/issues.json',
            body='{"issue":{"id":1,"project":{"id":2,"name":"test"},"tracker":{"id":1,"name":"Bug"}}}'
        )

        self.plugin.set_option('instance_url', 'http://localhost:3000', self.project)
        group = self.create_group(message='Hello world', culprit='foo.bar')

        request = self.request.get('/')
        request.user = AnonymousUser()
        form_data = {
            'title': 'Hello',
            'description': 'Fix this.',
        }
        assert self.plugin.create_issue(request, group, form_data) == 1

    @responses.activate
    def test_link_issue(self):
        responses.add(
            responses.GET,
            'http://localhost:3000/issues/1.json',
            body='{"issue":  {"id": 1, "subject": "redmine issue"}}'
        )
        responses.add(
            responses.PUT,
            'http://localhost:3000/issues/1.json',
            body=''
        )

        self.plugin.set_option('instance_url', 'http://localhost:3000', self.project)
        group = self.create_group(message='Hello world', culprit='foo.bar')

        request = self.request.get('/')
        request.user = AnonymousUser()
        form_data = {
            'comment': 'Hello',
            'issue_id': '1',
        }

        assert self.plugin.link_issue(request, group, form_data) == {'title': 'redmine issue'}
