import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Phoebe',
  description: 'My homelab cluster, powered by Talos Linux and Kubernetes.',
  base: '/phoebe/',
  lang: 'en-GB',
  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Components', link: '/components/' },
      { text: 'Workflows', link: '/flows/' }
    ],
    sidebar: [
      {
        text: 'Components',
        link: '/components/',
        items: [
          { text: 'Hardware', link: '/components/hardware' },
          {
            text: 'Infrastructure',
            collapsed: false,
            items: [
              { text: 'Talos', link: '/components/infrastructure/talos' },
              { text: 'Cilium', link: '/components/infrastructure/cilium' },
              { text: 'Envoy Gateway', link: '/components/infrastructure/envoy' },
              { text: 'Multus', link: '/components/infrastructure/multus' }
            ]
          },
          {
            text: 'Tools',
            collapsed: true,
            items: [
              { text: 'cert-manager', link: '/components/tools/cert-manager' },
              { text: 'External DNS', link: '/components/tools/external-dns' },
              { text: 'External Secrets', link: '/components/tools/external-secrets' },
              { text: 'Volsync', link: '/components/tools/volsync' }
            ]
          },
          {
            text: 'Services',
            collapsed: true,
            items: [
              { text: 'Cloudflare', link: '/components/services/cloudflare/' },
              { text: 'Gatus', link: '/components/services/gatus' },
              { text: 'Keycloak', link: '/components/services/keycloak' },
              {
                text: 'UpCloud',
                link: '/components/services/upcloud/',
                items: [
                  { text: 'Object storage', link: '/components/services/upcloud/object-storage' }
                ]
              },
              {
                text: 'Media',
                link: '/components/services/media/',
                collapsed: true,
                items: [
                  { text: 'Plex', link: '/components/services/media/plex' },
                  { text: 'qBittorrent', link: '/components/services/media/qbittorrent' },
                  { text: 'Radarr', link: '/components/services/media/radarr' },
                  { text: 'SABnzbd', link: '/components/services/media/sabnzbd' },
                  { text: 'Sonarr', link: '/components/services/media/sonarr' }
                ]
              }
            ]
          }
        ]
      },
      {
        text: 'Workflows',
        link: '/flows/',
        items: [
          { text: 'GitOps', link: '/flows/gitops' },
          { text: 'Updates', link: '/flows/updates' },
          { text: 'Backups', link: '/flows/backups' },
          {
            text: 'Restoration',
            collapsed: false,
            items: [
              { text: 'Restore an application', link: '/flows/restore-application' },
              { text: 'Restore PostgreSQL', link: '/flows/restore-postgres' }
            ]
          },
          {
            text: 'Maintenance',
            collapsed: false,
            items: [
              { text: 'Miroir maintenance', link: '/flows/maintenance' }
            ]
          }
        ]
      }
    ],
    search: { provider: 'local' },
    editLink: {
      pattern: 'https://github.com/hbjydev/phoebe/edit/main/docs/:path',
      text: 'Edit this page on GitHub'
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/hbjydev/phoebe' }
    ]
  },
  markdown: {
    config(md) {
      const fence = md.renderer.rules.fence!
      md.renderer.rules.fence = (tokens, index, options, env, self) => {
        const token = tokens[index]
        if (token.info.trim() === 'mermaid') {
          const code = md.utils.escapeHtml(JSON.stringify(token.content))
          return `<MermaidDiagram :code="${code}" />\n`
        }
        return fence(tokens, index, options, env, self)
      }
    }
  }
})
