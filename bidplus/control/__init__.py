"""Remote control plane (Google Sheet rendezvous) for the outbound-only box.

The box cannot be reached from outside, so a long-running agent (``bidplus.control.agent``)
*polls* a Google Sheet for whitelisted commands and *writes* run status + a per-bid list
back to it. All traffic is box -> Google. The Sheet is the only control surface, and every
command row is treated as untrusted input mapped through a fixed whitelist to a fixed argv —
never a shell, never eval.

Standing rule preserved: this layer triggers the scraper and reports FACTS only. It never
makes bid recommendations.
"""
