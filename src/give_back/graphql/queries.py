"""GraphQL query strings for give-back.

The main viability query fetches most data needed for Phase 1 signals in a single
API call. CONTRIBUTING.md text is fetched separately via REST (see CLAUDE.md).

Note: GitHub GraphQL orders PRs by CREATED_AT, not CLOSED_AT. Signal functions
apply the 12-month date filter on closedAt/mergedAt timestamps.
"""

VIABILITY_QUERY = """
query RepoViability($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    licenseInfo {
      spdxId
      name
      key
    }
    labels(first: 100) {
      nodes {
        name
      }
    }
    defaultBranchRef {
      target {
        ... on Commit {
          committedDate
        }
      }
    }
    releases(last: 5, orderBy: {field: CREATED_AT, direction: ASC}) {
      nodes {
        createdAt
        tagName
      }
    }
    issues(states: OPEN) {
      totalCount
    }
    closedIssues: issues(states: CLOSED) {
      totalCount
    }
    pullRequests(last: 50, states: [MERGED, CLOSED]) {
      nodes {
        state
        merged
        mergedAt
        closedAt
        createdAt
        author {
          login
        }
        authorAssociation
        comments(first: 5) {
          nodes {
            createdAt
            author {
              login
            }
            authorAssociation
          }
        }
        reviews(first: 1) {
          nodes {
            createdAt
          }
        }
      }
    }
  }
}
"""
