# Doggos publishing and Railway account follow-up

The site is served from the versioned `doggos-indigo` RustFS bucket on
Bandicoot. Its publishing settings, access policy and backup path are in the
[Doggos runbook](../runbooks/doggos-indigo.md).

Only these tasks remain unverified:

- [ ] **Nathan and Indigo: validate Blocs publishing from her iPad.** On the
  home network, use the settings in the **Doggos Indigo Publish** 1Password
  item. Publish the entire site, then make a one-page change and publish
  “just the changes”. Confirm both appear at `https://doggos.indigopod.au`.
  Command-line SFTP upload, download and deletion passed during the RustFS
  migration; that does not prove Blocs' own publishing behavior.
- [ ] **Nathan: close the Railway account and remove its unused API token.**
  The earlier migration recorded the final project, *Indigo's Stuff*, as
  deleted, but left account closure and deletion of the 1Password item
  `railway-api-token` to Nathan. Confirm the account has no remaining
  projects or billing obligations before closing it and removing the token.

Delete this file when both tasks are confirmed complete.
