mytardis-app-repos-consumer
===========================



Hooks for MyTardis to ingest public experiments from other Mytardises

Installation
------------

Clone into the MyTardis ``APPS`` directory as normal

Configuring
-----------

Added to the settings.py CERLERY_IMPORTS.  For example::


CELERY_IMPORTS = ("tardis.tardis_portal.tasks", "tardis.apps.reposconsumer.tasks" )


Added to task queue::

CELERYBEAT_SCHEDULE = {
      "verify-files": {
        "task": "tardis_portal.verify_files",
        "schedule": timedelta(seconds=30)
        },
        "transfer-experiments": {
         "task": "reposconsumer.transfer_experiments",
         "schedule": timedelta(seconds=30),
         "args": ("http://127.0.0.1:9000",)
       },
    }

Where the argument of the source of the mytardis application experiment feed.

Add application ``INSTALLED_APPS``.  For example::

    INSTALLED_APPS += ("tardis.apps.reposconsumer", )



