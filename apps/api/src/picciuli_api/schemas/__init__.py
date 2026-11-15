"""Request and response bodies of the REST API.

Conventions, shared with the library:

* amounts are integers in minor units (cents);
* quantities, prices and exchange rates are decimal numbers serialized as
  strings (for example `"1.25"`) so that no precision is lost;
* dates use the ISO format `YYYY-MM-DD`;
* `PATCH` bodies only change the fields they contain.
"""
