export const meta = {
  name: 'curax-import',
  description: 'Import parallèle Curax : taxonomies, classification articles, LCA + vulgarisation papers, keywords',
  whenToUse: 'Après `python3 scripts/import.py --scan infiles/` + préparation des fichiers de travail. args = méta-JSON produit par prep_import.py.',
  phases: [
    { title: 'Taxonomies', detail: 'un architecte par corpus (articles / papers)', model: 'opus' },
    { title: 'Articles', detail: 'classifier Opus + keywords Haiku par article' },
    { title: 'Publications', detail: 'LCA Opus + vulgarisation Sonnet + keywords Haiku par PDF' },
  ],
}

// args peut arriver JSON-encodé en string selon le chemin d'invocation — on normalise.
const input = typeof args === 'string' ? JSON.parse(args) : (args || {})
const A = input.articles || []
const P = input.papers || []

const TAXO_SCHEMA = {
  type: 'object',
  required: ['domains', 'observations'],
  properties: {
    domains: {
      type: 'object',
      additionalProperties: {
        type: 'object',
        required: ['name', 'description', 'icon'],
        properties: {
          name: { type: 'string' },
          description: { type: 'string' },
          icon: { type: 'string' },
        },
      },
    },
    observations: { type: 'string' },
  },
}

const CLASSIFY_SCHEMA = {
  type: 'object',
  required: ['domain', 'tags', 'quality_score', 'quality_note', 'title', 'description'],
  properties: {
    domain: { type: 'string' },
    tags: { type: 'array', items: { type: 'string' }, minItems: 1, maxItems: 3 },
    quality_score: { type: 'integer', minimum: 1, maximum: 10 },
    quality_note: { type: 'string' },
    title: { type: 'string' },
    description: { type: 'string' },
  },
}

const KEYWORDS_SCHEMA = {
  type: 'object',
  required: ['keywords'],
  properties: {
    keywords: { type: 'array', items: { type: 'string' }, minItems: 10, maxItems: 20 },
  },
}

const LCA_SCHEMA = {
  type: 'object',
  required: ['domain', 'tags', 'title', 'description', 'quality_note', 'authors',
             'year', 'journal', 'doi', 'robustness_scores', 'robustness_global', 'lca_html'],
  properties: {
    domain: { type: 'string' },
    tags: { type: 'array', items: { type: 'string' }, minItems: 1, maxItems: 3 },
    title: { type: 'string' },
    description: { type: 'string' },
    quality_note: { type: 'string' },
    authors: { type: 'array', items: { type: 'string' } },
    year: { type: 'integer' },
    journal: { type: 'string' },
    doi: { type: 'string' },
    robustness_scores: {
      type: 'object',
      required: ['question_recherche', 'design_experimental', 'taille_echantillon',
                 'qualite_metriques', 'controle_biais', 'reproductibilite',
                 'transparence_limitations', 'impact_nouveaute'],
      additionalProperties: { type: 'number', minimum: 0, maximum: 5 },
    },
    robustness_global: { type: 'number', minimum: 0, maximum: 5 },
    lca_html: { type: 'string' },
  },
}

const VULG_SCHEMA = {
  type: 'object',
  required: ['vulgarisation_html'],
  properties: { vulgarisation_html: { type: 'string' } },
}

function slugify(s, fallback) {
  const slug = String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
    .replace(/-+$/, '')
  return slug || fallback
}

// Retry 1 fois en cas d'échec terminal (agent() retourne null), puis on exclut l'item.
async function call(prompt, opts) {
  let r = await agent(prompt, opts)
  if (r === null) {
    log(`échec de ${opts.label || 'un agent'} — nouvelle tentative`)
    r = await agent(prompt + '\n\n(Seconde tentative après un échec.)', opts)
  }
  return r
}

async function articlesChain() {
  if (!A.length) return { taxonomy: null, items: [] }
  const taxonomy = await call(
    `Type=articles. Le corpus existant et les previews des nouveaux articles sont dans le fichier ${input.articlesTaxonomyFile} — lis-le en entier. Produis la taxonomie de domaines articles (en conservant les domaines existants sauf nécessité) et les observations transversales.`,
    { agentType: 'curax-taxonomy-architect', phase: 'Taxonomies', label: 'taxonomie-articles', schema: TAXO_SCHEMA }
  )
  if (!taxonomy) {
    log('taxonomie articles indisponible — articles exclus de cet import')
    return { taxonomy: null, items: [] }
  }
  const items = await parallel(A.map((a) => async () => {
    const pair = await parallel([
      () => call(
        `Taxonomie des domaines disponibles (choisis un slug existant): ${JSON.stringify(taxonomy.domains)}\nAuteur: ${a.author || 'inconnu'}. Source: ${a.source}.\nLis le texte complet de l'article dans le fichier ${a.textFile}, puis classifie-le : domain, tags (1-3), quality_score (1-10), quality_note, title, description.`,
        { agentType: 'curax-article-classifier', phase: 'Articles', label: `classifier:${a.filename}`, schema: CLASSIFY_SCHEMA }
      ),
      () => call(
        `Lis le début (environ 4000 premiers caractères) du fichier ${a.textFile}. Auteur: ${a.author || 'inconnu'}. Tags déjà assignés: aucun (la déduplication est faite en aval). Extrais 10 à 20 mots-clés cherchables.`,
        { agentType: 'curax-keyword-extractor', phase: 'Articles', label: `keywords:${a.filename}`, schema: KEYWORDS_SCHEMA }
      ),
    ])
    const cls = pair[0]
    const kw = pair[1]
    if (!cls) {
      log(`article exclu (classification échouée): ${a.filename}`)
      return null
    }
    const tags = cls.tags || []
    const keywords = ((kw && kw.keywords) || []).filter((k) => !tags.includes(k))
    return {
      filepath: a.filepath,
      source: a.source,
      author: a.author,
      domain: cls.domain,
      tags,
      quality_score: cls.quality_score,
      quality_note: cls.quality_note,
      title: cls.title,
      description: cls.description,
      keywords,
      slug: slugify(cls.title, a.provisional_slug),
    }
  }))
  return { taxonomy, items: items.filter(Boolean) }
}

async function papersChain() {
  if (!P.length) return { taxonomy: null, items: [] }
  const taxonomy = await call(
    `Type=papers. Le corpus existant et les previews des nouvelles publications sont dans le fichier ${input.papersTaxonomyFile} — lis-le en entier. Produis la taxonomie d'axes de recherche (en conservant les domaines existants sauf nécessité) et les observations transversales.`,
    { agentType: 'curax-taxonomy-architect', phase: 'Taxonomies', label: 'taxonomie-papers', schema: TAXO_SCHEMA }
  )
  if (!taxonomy) {
    log('taxonomie papers indisponible — publications exclues de cet import')
    return { taxonomy: null, items: [] }
  }
  const items = await parallel(P.map((p) => async () => {
    const trio = await parallel([
      () => call(
        `Taxonomie des axes de recherche disponibles (choisis un slug existant): ${JSON.stringify(taxonomy.domains)}\nLis le texte intégral de la publication dans le fichier ${p.textFile}, puis produis la LCA complète : métadonnées (title, authors, year, journal, doi, description, quality_note, domain, tags 1-3), les 8 scores de robustesse, la note globale indépendante (0-5) et le document HTML complet de la LCA en français (lca_html).`,
        { agentType: 'curax-paper-lca-analyst', phase: 'Publications', label: `lca:${p.filename}`, schema: LCA_SCHEMA }
      ),
      () => call(
        `Lis le texte de la publication dans le fichier ${p.textFile}. Extrais toi-même le titre et les auteurs de l'abstract. Rédige l'article de vulgarisation (~2000 mots, en français) et renvoie son HTML (corps seul) dans vulgarisation_html.`,
        { agentType: 'curax-paper-vulgarizer', phase: 'Publications', label: `vulgarisation:${p.filename}`, schema: VULG_SCHEMA }
      ),
      () => call(
        `Lis l'abstract dans le fichier ${p.abstractFile}. Tags déjà assignés: aucun (la déduplication est faite en aval). Extrais 10 à 20 mots-clés cherchables.`,
        { agentType: 'curax-keyword-extractor', phase: 'Publications', label: `keywords:${p.filename}`, schema: KEYWORDS_SCHEMA }
      ),
    ])
    const lca = trio[0]
    const vulg = trio[1]
    const kw = trio[2]
    if (!lca || !vulg) {
      log(`publication exclue (${!lca ? 'LCA' : 'vulgarisation'} échouée): ${p.filename}`)
      return null
    }
    const tags = lca.tags || []
    const keywords = ((kw && kw.keywords) || []).filter((k) => !tags.includes(k))
    return {
      filepath: p.filepath,
      domain: lca.domain,
      tags,
      title: lca.title,
      description: lca.description,
      quality_note: lca.quality_note,
      authors: lca.authors,
      year: lca.year,
      journal: lca.journal,
      doi: lca.doi,
      robustness_scores: lca.robustness_scores,
      robustness_global: lca.robustness_global,
      lca_html: lca.lca_html,
      vulgarisation_html: vulg.vulgarisation_html,
      keywords,
      slug: slugify(lca.title, p.fallback_slug),
    }
  }))
  return { taxonomy, items: items.filter(Boolean) }
}

// Les deux chaînes sont indépendantes : pas de barrière entre articles et papers.
const results = await parallel([articlesChain, papersChain])
const art = results[0] || { taxonomy: null, items: [] }
const pap = results[1] || { taxonomy: null, items: [] }

log(`Import prêt : ${art.items.length} article(s), ${pap.items.length} publication(s)`)

return {
  articles_taxonomy: art.taxonomy,
  papers_taxonomy: pap.taxonomy,
  articles: art.items,
  papers: pap.items,
  cleanup_infiles: true,
  infiles_dir: 'infiles',
}
