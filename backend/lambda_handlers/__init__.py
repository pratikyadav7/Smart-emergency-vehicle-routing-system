"""
AWS Lambda entry points (Person B's integration surface).

Named ``lambda_handlers`` rather than ``lambda`` because ``lambda`` is a
Python keyword and a package by that name cannot be imported or unit-tested.
The deployment path is unaffected: point each Lambda at
``backend.lambda_handlers.analyze.handler.handler`` /
``backend.lambda_handlers.reroute.handler.handler``.
"""
