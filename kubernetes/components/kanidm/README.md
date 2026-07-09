# KanIDM Component

This component provisions `kaniop`-based OIDC clients for services to use in a
consistent way.

## Arguments

| Key                                | Description                                                                                                                                                                         | Required? | Default                        |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ------------------------------ |
| `OIDC_DISPLAY_NAME`                | The display name to show to users in the KanIDM landing page.                                                                                                                       | No        | `${APP}`                       |
| `OIDC_IMAGE_URL`                   | The app icon to use in KanIDM for this service.                                                                                                                                     | No        | The selfh.st icon for `${APP}` |
| `OIDC_ORIGIN`                      | The JavaScript/Referrer origin for this service.                                                                                                                                    | Yes       |                                |
| `OIDC_REDIRECT_URLS`               | The redirect urls to allow for this service. Provided in the form of a YAML array (i.e. `OIDC_REDIRECT_URLS: '["https://service.hayden.moe"]'`)                                     | Yes       |                                |
| `OIDC_SECRET_ROTATION_ENABLED`     | Whether or not to enable rotation for the Client Secret for this OAuth2 client.                                                                                                     | No        | `true`                         |
| `OIDC_SECRET_ROTATION_PERIOD_DAYS` | How often in days to rotate the client secret if secret rotation is enabled.                                                                                                        | No        | `90`                           |
| `OIDC_SECRET_KEY_ALIASES`          | A YAML dictionary containing Client ID and Client Secret key aliases for the generated secret. In the format `{clientId: [<client id keys>], clientSecret: [<client secret keys>]}` | No        | `{}`                           |
| `OIDC_USERS_GROUP_MEMBERS`         | A list of usernames to add to the `${APP}_users` group for this service.                                                                                                            | No        | `[]`                           |
| `OIDC_ADMIN_GROUP_MEMBERS`         | A list of usernames to add to the `${APP}_admins` group for this service.                                                                                                           | No        | `[]`                           |

## Example

```yaml
components:
  - ../../../../components/kanidm/private
postBuild:
  substitute:
    APP: *app
    NAMESPACE: *namespace
    OIDC_DISPLAY_NAME: NTFY!
    OIDC_IMAGE_URL: https://picsum.photos/256/256
    OIDC_ORIGIN: https://ntfy.hayden.moe
    OIDC_REDIRECT_URLS: '["https://ntfy.hayden.moe"]'
    OIDC_SECRET_ROTATION_ENABLED: 'false'
    OIDC_SECRET_ROTATION_PERIOD_DAYS: '30'
    OIDC_SECRET_KEY_ALIASES: '{clientId: [key], clientSecret: [clientSec]}'
    OIDC_USERS_GROUP_MEMBERS: '[invisible, hayden]'
    OIDC_ADMINS_GROUP_MEMBERS: '[hayden]'
```
