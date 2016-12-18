from __future__ import absolute_import
import json
import logging

from sentry.exceptions import PluginError
from sentry.plugins.bases.issue2 import IssuePlugin2
from sentry.utils.http import absolute_uri
from sentry_plugins.base import CorePluginMixin
from sentry_plugins.utils import get_secret_field_config

from .client import RedmineClient, RedmineError


class RedminePlugin(CorePluginMixin, IssuePlugin2):
    description = "Integrate Redmine issue tracking by linking a user account to a project."
    slug = 'redmine'
    title = 'Redmine'
    conf_title = title
    conf_key = 'redmine'
    logger = logging.getLogger('sentry.plugins.redmine')

    def is_configured(self, request, project, **kwargs):
        return all((self.get_option(k, project) for k in ('instance_url', 'key')))

    def get_client(self, project):
        return RedmineClient(
            host=self.get_option('instance_url', project),
            key=self.get_option('key', project),
        )

    def create_issue(self, request, group, form_data, **kwargs):
        """
        Create a Redmine issue
        """
        issue_dict = {
            'project_id': self.get_option('project_id', group.project),
            'tracker_id': self.get_option('tracker_id', group.project),
            'priority_id': self.get_option('priority_id', group.project),
            'subject': form_data['title'].encode('utf-8'),
            'description': form_data['description'].encode('utf-8'),
        }

        extra_fields_str = self.get_option('extra_fields', group.project)
        if extra_fields_str:
            extra_fields = json.loads(extra_fields_str)
        else:
            extra_fields = {}
        issue_dict.update(extra_fields)

        client = self.get_client(group.project)
        response = client.create_issue(issue_dict)
        return response['issue']['id']

    def get_issue_url(self, group, issue_id, **kwargs):
        host = self.get_option('instance_url', group.project)
        return '{}/issues/{}'.format(host.rstrip('/'), issue_id)

    def get_issue_label(self, group, issue_id, **kwargs):
        return 'Redmine-{}'.format(issue_id)

    def get_configure_plugin_fields(self, request, project, **kwargs):
        key = self.get_option('key', project)
        help_text = ('Your API key is available on your account page after enabling the '
                     'Rest API (Administration -> Settings -> Authentication)')
        secret_field = get_secret_field_config(key, help_text, include_prefix=True)
        secret_field.update({
            'name': 'key',
            'label': 'API key',
            'placeholder': 'e.g. a9877d72b6d13b23410a7109b35e88bc'
        })
        fields = [{
            'name': 'instance_url',
            'label': 'Redmine Instance URL',
            'type': 'text',
            'placeholder': 'e.g. http://bugs.redmine.org',
            'help': 'Redmine instance URL, it must be accessible from the Sentry server'
        }, secret_field]

        has_credentials = all((self.get_option(k, project) for k in ('instance_url', 'key')))
        if has_credentials:
            client = self.get_client(project)
            try:
                projects = client.get_projects()
            except RedmineError:
                # Do not show additional fields (projects, priorities, etc.)
                return fields
            else:
                project_choices = [
                    (p['id'], '{} ({})'.format(p['name'], p['identifier']))
                    for p in projects['projects']
                ]
        else:
            return fields
        default_project_choice = project_choices[0][0] if project_choices else ''

        tracker_choices = []
        try:
            trackers = client.get_trackers()
        except RedmineError:
            pass
        else:
            tracker_choices = [
                (p['id'], p['name'])
                for p in trackers['trackers']
            ]
        default_tracker_choice = tracker_choices[0][0] if tracker_choices else ''

        priority_choices = []
        try:
            priorities = client.get_priorities()
        except RedmineError:
            pass
        else:
            priority_choices = [
                (p['id'], p['name'])
                for p in priorities['issue_priorities']
            ]
        default_priority_choice = priority_choices[0][0] if priority_choices else ''

        return fields + [{
            'name': 'project_id',
            'label': 'Project',
            'type': 'select',
            'choices': project_choices,
            'required': True,
            'default': default_project_choice,
        }, {
            'name': 'tracker_id',
            'label': 'Tracker',
            'type': 'select',
            'choices': tracker_choices,
            'required': True,
            'default': default_tracker_choice,
        }, {
            'name': 'priority_id',
            'label': 'Priority',
            'type': 'select',
            'choices': priority_choices,
            'required': True,
            'default': default_priority_choice,
        }, {
            'name': 'extra_fields',
            'label': 'Extra Fields',
            'type': 'textarea',
            'required': False,
            'placeholder': '{"custom_fields": [...]}',
            'help': 'Extra attributes (custom fields, status id, etc.) in JSON format',
        }]

    def link_issue(self, request, group, form_data, **kwargs):
        client = self.get_client(group.project)
        try:
            issue = client.get_issue(form_data['issue_id'])
        except RedmineError as e:
            raise PluginError(unicode(e))

        comment = form_data.get('comment')
        if comment:
            try:
                client.add_comment(form_data['issue_id'], comment)
            except RedmineError as e:
                raise PluginError(unicode(e))

        return {
            'title': issue["issue"]["subject"],
        }

    def get_link_existing_issue_fields(self, request, group, event, **kwargs):
        return [{
            'name': 'issue_id',
            'label': 'Issue ID',
            'default': '',
            'type': 'text',
        }, {
            'name': 'comment',
            'label': 'Comment',
            'default': absolute_uri(group.get_absolute_url()),
            'type': 'textarea',
            'help': 'Leave blank if you don\'t want to add a comment to the Redmine issue.',
            'required': False,
        }]

    def get_group_description(self, request, group, event):
        output = [
            absolute_uri(group.get_absolute_url()),
        ]
        body = self.get_group_body(request, group, event)
        if body:
            output.extend([
                '',
                '<pre>',
                body,
                '</pre>',
            ])
        return '\n'.join(output)

    def validate_config_field(self, project, name, value, actor=None):
        value = super(RedminePlugin, self).validate_config_field(project, name, value, actor)
        if name == 'extra_fields' and value:
            # Ensure that extra fields are represented by a valid JSON object
            extra_fields_value = value.strip()
            if not extra_fields_value:
                return ''
            try:
                extra_fields_dict = json.loads(extra_fields_value)
            except ValueError:
                raise PluginError('Invalid JSON specified')

            if not isinstance(extra_fields_dict, dict):
                raise PluginError('JSON dictionary must be specified')

            return json.dumps(extra_fields_dict, indent=4)
        return value
