Expfactory Deploy
=================

Django project for the managment and deployment of batteries of experiments.

History
-------

The repos and their purpose from first iteration of Expfactory:

-  `expfactory-experiments <https://github.com/expfactory/experiments>`_: Holds large nunmber of jspsych experiments currated by Poldrack Lab.
- `expfactory-python <https://github.com/expfactory/expfactory-python>`_:
  Python module/cli that would take experiments and compose them into
  batteries. Could serve batteries locally via a flask application.
- `expfactory-battery <https://github.com/expfactory/expfactory-battery>`_: Held
  static files used across all experiments, and templates used by
  expfactory-python to help glue expeirments together.
- `expfactory-docker <https://github.com/expfactory/expfactory-docker>`_:
  Django project to serve batteries and store results generated by them.

And from the The second iteration of Expfactory:

- `expfactory-experiments (github org)
  <https://github.com/expfactory-experiments>`_: Seprated each experiment into
  their own repository.
- `expfactory <https://github.com/expfactory/expfactory>`_: A utility to mint
  container images that allow given batteries to be reproducibly run.

About
----

This repository is intended as a replacement for
`expfactory-docker<https://github.com/expfactory/expfactory-docker>`_ and
seeks to expand on the ease of use of the first iteration of expfactory and
integrate the tenets of reproducibility from the second iteration. 
