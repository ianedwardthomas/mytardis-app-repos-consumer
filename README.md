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



Add application ``INSTALLED_APPS``.  For example::

    INSTALLED_APPS += ("tardis.apps.reposconsumer", )



