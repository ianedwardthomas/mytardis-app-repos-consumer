mytardis-app-repos-consumer
===========================



Hooks for MyTardis to ingest public experiments from other Mytardises

Installation
------------

Clone into the MyTardis ``APPS`` directory as ``reposconsumer``
e.g., ``git clone https://github.com/ianedwardthomas/mytardis-app-repos-consumer reposconsumer``

Configuring
-----------

Added to the settings.py CERLERY_IMPORTS.  For example::

    CELERY_IMPORTS = ("tardis.tardis_portal.tasks", "tardis.apps.reposconsumer.tasks" )


Added to task queue::

    CELERYBEAT_SCHEDULE = {
        ...
        "consume-experiments": {
         "task": "reposconsumer.consume_experiments",
         "schedule": timedelta(seconds=30),
         "args": ("http://127.0.0.1:9000",) # the destination to pull experiments
       },
    }

Where the argument of the source of the mytardis application experiment feed.

*Important*: The set of schemas on the site must match those used by experiements to be ingested on the remote site.  This can be loaded via the admin tool, for example.

Add unique key entry to settings.py::

    KEY_NAME = "experiment_key"
    KEY_NAMESPACE = "http://tardis.edu.au/schemas/experimentkey"
    
and add the schema and parameterName using the admin tool.
    
Add application ``INSTALLED_APPS``.  For example::

    INSTALLED_APPS += ("tardis.apps.reposconsumer", )

Then start celery as usual.