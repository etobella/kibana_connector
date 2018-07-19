# Copyright 2017 Creu Blanca
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
import psycopg2
import json
from datetime import datetime

import odoo
from odoo.addons.component.core import AbstractComponent
from odoo.addons.connector.exception import RetryableJobError
import elasticsearch

ISO_FORMAT = '%Y-%m-%dT%H:%M:%S.%f'
_logger = logging.getLogger(__name__)


class ElasticsearchBaseExporter(AbstractComponent):
    """ Base exporter for the Elasticsearch """

    _name = 'elasticsearch.base.exporter'
    _inherit = ['base.exporter', 'base.elasticsearch.connector']
    _usage = 'record.exporter'
    _exporter_failure_timeout = 2

    def _lock(self, binding):
        """ Lock the binding record.
        Lock the binding record so we are sure that only one export
        job is running for this record if concurrent jobs have to export the
        same record.
        When concurrent jobs try to export the same record, the first one
        will lock and proceed, the others will fail to lock and will be
        retried later.
        This behavior works also when the export becomes multilevel
        with :meth:`_export_dependencies`. Each level will set its own lock
        on the binding record it has to export.
        """
        sql = ("SELECT id FROM %s WHERE ID = %%s FOR UPDATE NOWAIT" %
               self.model._table)
        try:
            self.env.cr.execute(sql, (binding.id,),
                                log_exceptions=False)
        except psycopg2.OperationalError:
            _logger.info('A concurrent job is already exporting the same '
                         'record (%s with id %s). Job delayed later.',
                         self.model._name, binding.id)
            raise RetryableJobError(
                'A concurrent job is already exporting the same record '
                '(%s with id %s). The job will be retried later.' %
                (self.model._name, binding.id),
                seconds=self._exporter_failure_timeout)

    def create(self, binding, *args, **kwargs):
        self._lock(binding)
        index = binding.index
        doc_type = binding.doc_type
        es = elasticsearch.Elasticsearch(
            hosts=binding.backend_id.get_hosts())
        data = json.dumps(kwargs['data'])
        logging.info(data)
        es.create(index, doc_type, binding.id, body=data)
        binding.sync_date = kwargs['sync_date']
        if not odoo.tools.config['test_enable']:
            self.env.cr.commit()  # noqa
        self._after_export()
        return True

    def delete(self, binding, *args, **kwargs):
        """ Run the synchronization
        :param binding: binding record to export
        """
        self._lock(binding)
        sync_date = datetime.strptime(kwargs['sync_date'], ISO_FORMAT)
        if (
            not binding.sync_date or
            sync_date >= datetime.strptime(binding.sync_date, ISO_FORMAT)
        ):
            index = binding.index
            doc_type = binding.doc_type
            es = elasticsearch.Elasticsearch(
                hosts=binding.backend_id.get_hosts())
            es.delete(index, doc_type, binding.id)
            binding.sync_date = kwargs['sync_date']
            if not odoo.tools.config['test_enable']:
                self.env.cr.commit()  # noqa
            binding.sync_date = kwargs['sync_date']
        else:
            _logger.info(
                'Record from %s with id %s has already been sended (%s), so it'
                ' is deprecated ' % (
                    self.model._name, binding.id, kwargs['sync_date']
                )
            )
        # Commit so we keep the external ID when there are several
        # exports (due to dependencies) and one of them fails.
        # The commit will also release the lock acquired on the binding
        # record
        if not odoo.tools.config['test_enable']:
            self.env.cr.commit()  # noqa
        self._after_export()
        return True

    def update(self, binding, *args, **kwargs):
        """ Run the synchronization
        :param binding: binding record to export
        """
        self._lock(binding)
        sync_date = datetime.strptime(kwargs['sync_date'], ISO_FORMAT)
        if (
            not binding.sync_date or
            sync_date >= datetime.strptime(binding.sync_date, ISO_FORMAT)
        ):
            index = binding.index
            doc_type = binding.doc_type
            es = elasticsearch.Elasticsearch(
                hosts=binding.backend_id.get_hosts())
            data = json.dumps(kwargs['data'])
            logging.info(data)
            es.update(index, doc_type, binding.id, body=data)
            binding.sync_date = kwargs['sync_date']
            if not odoo.tools.config['test_enable']:
                self.env.cr.commit()  # noqa
            binding.sync_date = kwargs['sync_date']
        else:
            _logger.info(
                'Record from %s with id %s has already been sended (%s), so it'
                ' is deprecated ' % (
                    self.model._name, binding.id, kwargs['sync_date']
                )
            )
        # Commit so we keep the external ID when there are several
        # exports (due to dependencies) and one of them fails.
        # The commit will also release the lock acquired on the binding
        # record
        if not odoo.tools.config['test_enable']:
            self.env.cr.commit()  # noqa
        self._after_export()
        return True

    def _after_export(self):
        """ Can do several actions after exporting a record"""
        pass
