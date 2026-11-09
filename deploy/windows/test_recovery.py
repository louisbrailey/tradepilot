"""Documented SCM handle contract, with no actual SCM operations."""
import sys
import types
import unittest
from unittest.mock import patch
import configure_recovery


class FakeSCM(types.SimpleNamespace):
    SC_MANAGER_CONNECT=1
    SERVICE_QUERY_STATUS=4
    SERVICE_CHANGE_CONFIG=2
    SERVICE_START=16
    SERVICE_STOPPED=1
    SERVICE_RUNNING=4
    SERVICE_CONFIG_FAILURE_ACTIONS=2
    SC_ACTION_RESTART=1
    SC_ACTION_NONE=0

    def __init__(self, running=False, fail=False):
        super().__init__();self.handles=[];self.closed=[];self.configurations=[]
        self.running=running;self.fail=fail;self.manager=object()

    def OpenSCManager(self, machine, database, access):
        if machine is not None or database is not None or access!=self.SC_MANAGER_CONNECT:raise AssertionError('Local connect-only manager required')
        return self.manager

    def OpenService(self, manager, name, access):
        if manager is not self.manager:raise AssertionError('Wrong manager')
        handle=(name,access);self.handles.append(handle);return handle

    def QueryServiceStatus(self, handle):
        if not handle[1]&self.SERVICE_QUERY_STATUS:raise PermissionError('QUERY_STATUS required')
        return (0,self.SERVICE_RUNNING if self.running else self.SERVICE_STOPPED)

    def ChangeServiceConfig2(self, handle, level, settings):
        required=self.SERVICE_CHANGE_CONFIG|self.SERVICE_START
        if handle[1]&required!=required:raise PermissionError('Restart recovery requires CHANGE_CONFIG and START')
        if level!=self.SERVICE_CONFIG_FAILURE_ACTIONS:raise AssertionError('Unexpected configuration')
        if self.fail:raise OSError('Synthetic API failure')
        self.configurations.append((handle[0],settings))

    def CloseServiceHandle(self, handle):self.closed.append(handle)


class RecoveryContractTests(unittest.TestCase):
    def test_restart_contract_succeeds_without_starting_or_widening_permissions(self):
        api=FakeSCM()
        with patch.dict(sys.modules,{'win32service':api}):configure_recovery.configure()
        self.assertEqual([name for name,_ in api.configurations],list(configure_recovery.SERVICES))
        for _,settings in api.configurations:
            self.assertEqual(settings,{'ResetPeriod':86400,'RebootMsg':'','Command':'','Actions':[(1,15000),(1,30000),(1,60000),(0,0)]})
        self.assertCountEqual(api.closed,[api.manager,*api.handles])
        self.assertTrue(all(access==api.SERVICE_QUERY_STATUS|api.SERVICE_CHANGE_CONFIG|api.SERVICE_START for _,access in api.handles))

    def test_running_service_refuses_changes_and_closes_handles(self):
        api=FakeSCM(running=True)
        with patch.dict(sys.modules,{'win32service':api}),self.assertRaisesRegex(ValueError,'stopped'):configure_recovery.configure()
        self.assertEqual(api.configurations,[])
        self.assertCountEqual(api.closed,[api.manager,*api.handles])

    def test_native_failure_closes_service_and_manager(self):
        api=FakeSCM(fail=True)
        with patch.dict(sys.modules,{'win32service':api}),self.assertRaises(OSError):configure_recovery.configure()
        self.assertCountEqual(api.closed,[api.manager,*api.handles])


if __name__=='__main__':unittest.main()
