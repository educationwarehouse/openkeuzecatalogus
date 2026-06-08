# py4web Integration

## Flash Alerts

`flash` is the py4web flash fixture exposed by `py4web/apps/_default/fixtures/__init__.py` as `flash = auth.flash`.

Python code can use it in two ways:
- Generic controllers import `flash` from `..fixtures` and call `flash.set("message")` or `flash.set("message", "alert-success")`.
- Auth-specific code uses `AppAuth.flash_error(...)`, `flash_success(...)`, `flash_warning(...)`, or `flash_info(...)`, which delegate to `self.flash.set(...)`.

Rendering flow:
- `py4web/apps/_default/templates/layout.html` reads the flash object from the template globals and emits a `py4web-flash` template element.
- `py4web/apps/_default/assets/js/bootstrap-flash.js` turns that template into a dismissible Bootstrap alert in the top-right corner of the page.
