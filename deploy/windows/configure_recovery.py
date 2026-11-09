"""Owner-invoked fixed SCM recovery configuration; never starts a service."""
SERVICES = ('TradePilot', 'TradePilotOllama', 'TradePilotNetworkStatus')


def configure():
    import win32service as scm
    manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
    try:
        for name in SERVICES:
            # Restart actions require START on the handle even though this
            # operation only configures recovery and never starts a service.
            service = scm.OpenService(manager, name, scm.SERVICE_QUERY_STATUS | scm.SERVICE_CHANGE_CONFIG | scm.SERVICE_START)
            try:
                if scm.QueryServiceStatus(service)[1] != scm.SERVICE_STOPPED:
                    raise ValueError('All services must be stopped')
                scm.ChangeServiceConfig2(service, scm.SERVICE_CONFIG_FAILURE_ACTIONS,
                    {'ResetPeriod': 86400, 'RebootMsg': '', 'Command': '',
                     'Actions': [(scm.SC_ACTION_RESTART, 15000), (scm.SC_ACTION_RESTART, 30000),
                                 (scm.SC_ACTION_RESTART, 60000), (scm.SC_ACTION_NONE, 0)]})
            finally: scm.CloseServiceHandle(service)
    finally: scm.CloseServiceHandle(manager)


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 1: raise SystemExit('No arguments supported')
    configure()
