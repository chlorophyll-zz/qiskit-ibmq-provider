# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2019.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""IBMQJob Test."""

import time
from unittest import mock, skip
import re

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.providers.jobstatus import JobStatus, JOB_FINAL_STATES
from qiskit.providers.ibmq.job.exceptions import IBMQJobFailureError, JobError
from qiskit.providers.ibmq.api.clients.account import AccountClient
from qiskit.providers.ibmq.exceptions import IBMQBackendValueError
from qiskit.compiler import assemble, transpile

from ..jobtestcase import JobTestCase
from ..decorators import requires_provider, slow_test_on_device


class TestIBMQJobAttributes(JobTestCase):
    """Test ibmqjob module."""

    def setUp(self):
        super().setUp()
        self._qc = _bell_circuit()

    @requires_provider
    def test_job_id(self, provider):
        """Test getting a job id."""
        backend = provider.get_backend('ibmq_qasm_simulator')

        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        job = backend.run(qobj)
        self.log.info('job_id: %s', job.job_id())
        self.assertTrue(job.job_id() is not None)

    @requires_provider
    def test_get_backend_name(self, provider):
        """Test getting a backend name."""
        backend = provider.get_backend('ibmq_qasm_simulator')

        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        job = backend.run(qobj)
        self.assertTrue(job.backend().name() == backend.name())

    @slow_test_on_device
    def test_running_job_properties(self, provider, backend):  # pylint: disable=unused-argument
        """Test fetching properties of a running job."""
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        job = backend.run(qobj)
        _ = job.properties()

    @requires_provider
    def test_job_name(self, provider):
        """Test using job names on a simulator."""
        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)

        # Use a unique job name
        job_name = str(time.time()).replace('.', '')
        job_id = backend.run(qobj, job_name=job_name).job_id()
        job = provider.backends.retrieve_job(job_id)
        self.assertEqual(job.name(), job_name)

        # Check using partial matching.
        job_name_partial = job_name[8:]
        retrieved_jobs = provider.backends.jobs(backend_name=backend.name(),
                                                job_name=job_name_partial)
        self.assertGreaterEqual(len(retrieved_jobs), 1)
        retrieved_job_ids = {job.job_id() for job in retrieved_jobs}
        self.assertIn(job_id, retrieved_job_ids)

        # Check using regular expressions.
        job_name_regex = '^{}$'.format(job_name)
        retrieved_jobs = provider.backends.jobs(backend_name=backend.name(),
                                                job_name=job_name_regex)
        self.assertEqual(len(retrieved_jobs), 1)
        self.assertEqual(job_id, retrieved_jobs[0].job_id())

    @requires_provider
    def test_duplicate_job_name(self, provider):
        """Test multiple jobs with the same custom job name using a simulator."""
        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)

        # Use a unique job name
        job_name = str(time.time()).replace('.', '')
        job_ids = set()
        for _ in range(2):
            job_ids.add(backend.run(qobj, job_name=job_name).job_id())

        retrieved_jobs = provider.backends.jobs(backend_name=backend.name(),
                                                job_name=job_name)

        self.assertEqual(len(retrieved_jobs), 2)
        retrieved_job_ids = {job.job_id() for job in retrieved_jobs}
        self.assertEqual(job_ids, retrieved_job_ids)
        for job in retrieved_jobs:
            self.assertEqual(job.name(), job_name)

    @skip('Skipping until staging device is fixed.')
    @slow_test_on_device
    def test_error_message_device(self, provider, backend):  # pylint: disable=unused-argument
        """Test retrieving job error messages from a device backend."""
        qc_new = transpile(self._qc, backend)
        qobj = assemble([qc_new, qc_new], backend=backend)
        qobj.experiments[1].instructions[1].name = 'bad_instruction'

        job = backend.run(qobj)
        with self.assertRaises(IBMQJobFailureError):
            job.result(timeout=300, partial=False)

        message = job.error_message()
        self.assertTrue(message)
        self.assertIsNotNone(re.search(r'Error code: [0-9]{4}\.$', message), message)

        r_message = provider.backends.retrieve_job(job.job_id()).error_message()
        self.assertTrue(r_message)
        self.assertIsNotNone(re.search(r'Error code: [0-9]{4}\.$', r_message), r_message)

    @requires_provider
    def test_error_message_simulator(self, provider):
        """Test retrieving job error messages from a simulator backend."""
        backend = provider.get_backend('ibmq_qasm_simulator')

        qc_new = transpile(self._qc, backend)
        qobj = assemble([qc_new, qc_new], backend=backend)
        qobj.experiments[1].instructions[1].name = 'bad_instruction'

        job = backend.run(qobj)
        with self.assertRaises(IBMQJobFailureError):
            job.result()

        message = job.error_message()
        self.assertIn('Experiment 1: ERROR', message)

        r_message = provider.backends.retrieve_job(job.job_id()).error_message()
        self.assertIn('Experiment 1: ERROR', r_message)

    @requires_provider
    def test_error_message_validation(self, provider):
        """Test retrieving job error message for a validation error."""
        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend), shots=10000)
        job = backend.run(qobj)
        with self.assertRaises(IBMQJobFailureError):
            job.result()

        message = job.error_message()
        self.assertNotIn("Unknown", message)

        # TODO Verify error code is in the message after API update
        r_message = provider.backends.retrieve_job(job.job_id()).error_message()
        self.assertEqual(message, r_message)

    @requires_provider
    def test_refresh(self, provider):
        """Test refreshing job data."""
        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        job = backend.run(qobj)
        job._wait_for_completion()

        rjob = provider.backends.jobs(db_filter={'id': job.job_id()})[0]
        self.assertFalse(rjob._time_per_step)
        rjob.refresh()
        self.assertEqual(rjob._time_per_step, job._time_per_step)

    @requires_provider
    def test_time_per_step(self, provider):
        """Test retrieving time per step."""
        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        job = backend.run(qobj)
        job.result()
        self.assertTrue(job.time_per_step())

        rjob = provider.backends.jobs(db_filter={'id': job.job_id()})[0]
        self.assertTrue(rjob.time_per_step())

    @requires_provider
    def test_new_job_attributes(self, provider):
        """Test job with new attributes."""
        def _mocked__api_job_submit(*args, **kwargs):
            submit_info = original_submit(*args, **kwargs)
            submit_info.update({'batman': 'bruce'})
            return submit_info

        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        original_submit = backend._api.job_submit
        with mock.patch.object(AccountClient, 'job_submit',
                               side_effect=_mocked__api_job_submit):
            job = backend.run(qobj)

        self.assertEqual(job.batman, 'bruce')

    @requires_provider
    def test_queue_info(self, provider):
        """Test retrieving queue information."""
        # Find the most busy backend.
        backend = max([b for b in provider.backends(simulator=False) if b.status().operational],
                      key=lambda b: b.status().pending_jobs)
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        leave_states = list(JOB_FINAL_STATES) + [JobStatus.RUNNING]
        job = backend.run(qobj)
        queue_info = None
        for _ in range(10):
            queue_info = job.queue_info()
            # Even if job status is QUEUED, queue information may not be
            # immediately available.
            if (job._status is JobStatus.QUEUED and job.queue_position() is not None) or \
                    job._status in leave_states:
                break
            time.sleep(0.5)

        if job._status is JobStatus.QUEUED and job.queue_position() is not None:
            self.log.debug("Job id=%s, queue info=%s, queue position=%s",
                           job.job_id(), queue_info, job.queue_position())
            msg = "Job {} is queued but has no ".format(job.job_id())
            self.assertIsNotNone(queue_info, msg + "queue info.")
            for attr, value in queue_info.__dict__.items():
                self.assertIsNotNone(value, msg + attr)
            self.assertTrue(all(0 < priority <= 1.0 for priority in [
                queue_info.hub_priority, queue_info.group_priority, queue_info.project_priority]),
                            "Unexpected queue info {} for job {}".format(queue_info, job.job_id()))
        else:
            self.assertIsNone(job.queue_position())
            self.log.warning("Unable to retrieve queue information")

        # Cancel job so it doesn't consume more resources.
        try:
            job.cancel()
        except JobError:
            pass

    @requires_provider
    def test_invalid_job_share_level(self, provider):
        """Test setting a non existent share level for a job."""
        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        with self.assertRaises(IBMQBackendValueError) as context_manager:
            backend.run(qobj, job_share_level='invalid_job_share_level')
        self.assertIn('not a valid job share', context_manager.exception.message)

    @requires_provider
    def test_share_job_in_project(self, provider):
        """Test successfully sharing a job within a shareable project."""
        backend = provider.get_backend('ibmq_qasm_simulator')
        qobj = assemble(transpile(self._qc, backend=backend), backend=backend)
        job = backend.run(qobj, job_share_level='project')

        retrieved_job = backend.retrieve_job(job.job_id())
        self.assertEqual(getattr(retrieved_job, 'share_level'), 'project')


def _bell_circuit():
    qr = QuantumRegister(2, 'q')
    cr = ClassicalRegister(2, 'c')
    qc = QuantumCircuit(qr, cr)
    qc.h(qr[0])
    qc.cx(qr[0], qr[1])
    qc.measure(qr, cr)
    return qc
