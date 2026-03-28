"""GraphQL query strings for give-back.

The main viability query fetches repo metadata in a single API call.
PRs are fetched separately via PULL_REQUESTS_PAGE_QUERY with cursor-based
pagination (50 per page, stops when PRs are older than the signal window).
CONTRIBUTING.md text is fetched separately via REST (see CLAUDE.md).
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
  }
}
"""

PULL_REQUESTS_PAGE_QUERY = """
query PullRequestsPage($owner: String!, $repo: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequests(last: 50, states: [MERGED, CLOSED], before: $cursor) {
      pageInfo {
        hasPreviousPage
        startCursor
      }
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
            author {
              login
            }
            authorAssociation
          }
        }
      }
    }
  }
}
"""
