"""PyInstaller's entry script. See DECISIONS.md section 15.

This file exists only because PyInstaller freezes a *script*, and a script runs
as `__main__` -- so `app/launcher.py`, whose imports are relative to the `app`
package, cannot itself be the frozen entry point. Everything real is in
`app.launcher`; keep this file a stub so there is no second place where launch
behavior lives.
"""

from app.launcher import main

if __name__ == "__main__":
    main()
