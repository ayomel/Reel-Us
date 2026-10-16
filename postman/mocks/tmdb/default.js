const http = require('http');

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (req.method !== 'GET' || url.pathname !== '/3/search/tv') {
    res.writeHead(501, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ error: 'Endpoint not modeled' }));
  }

  const query = url.searchParams.get('query') || '';
  if (query === 'upstream-error') {
    res.writeHead(500, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ status_message: 'Simulated TMDB failure' }));
  }

  res.writeHead(200, { 'content-type': 'application/json' });
  if (query.toLowerCase() !== 'breaking bad') {
    return res.end(JSON.stringify({ page: 1, results: [], total_pages: 1, total_results: 0 }));
  }
  res.end(JSON.stringify({
    page: 1,
    results: [{
      adult: false,
      backdrop_path: '/example.jpg',
      genre_ids: [18, 80],
      id: 1396,
      origin_country: ['US'],
      original_language: 'en',
      original_name: 'Breaking Bad',
      overview: 'A chemistry teacher turns to making methamphetamine.',
      popularity: 100,
      poster_path: '/breaking-bad.jpg',
      first_air_date: '2008-01-20',
      name: 'Breaking Bad',
      vote_average: 8.9,
      vote_count: 10000,
    }],
    total_pages: 1,
    total_results: 1,
  }));
}).listen(process.env.PORT);
