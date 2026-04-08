import http from 'k6/http';
import secrets from 'k6/secrets'
import { check } from 'k6';

export const options = {
  vus: 40,
  duration: '90s',
};

export default async () => {
  const url = 'https://data-dev.lsst.cloud/muster/auth/fail'
  const token = await secrets.get("gafaelfawr_token")
  const res = await http.asyncRequest('GET', url, null, {
    headers: {
      "Authorization": `Bearer ${token}`
    }
  });

  check(res, { "status is 200": (res) => res.status === 200 });
}
