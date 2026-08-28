"""Reserved delivery boundary for authenticated operational APIs.

Expensive jobs and provider calls must be added here only after authentication and
authorization exist. They must not be exposed through the anonymous public API.
"""
