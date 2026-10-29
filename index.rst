################################
Gateway migration for Gafaelfawr
################################

.. abstract::

   Gafaelfawr, the identity management and access control system for Phalanx environments including the Rubin Science Platform, is currently tightly integrated with ingress-nginx. This ingress provider will no longer be maintained after March 2026, and Kubernetes is encouraging a migration to the new Gateway API. This tech note outlines the planned transition process and necessary changes for Gafaelfawr.

.. note::

   This is part of a tech note series on identity management for the Rubin Science Platform.
   The other two primary documents are :dmtn:`224`, which describes the implementation; and :sqr:`069`, which provides a history and analysis of the decisions underlying the design and implementation.
   See the `references section of DMTN-224 <https://dmtn-224.lsst.io/#references>`__ for a complete list of related documents.

Problem statement
=================

Gafaelfawr_ is the identity management and access control system for all Phalanx_ environments including the Rubin Science Platform.
It currently runs primarily as an NGINX ``auth_request`` handler and is tightly integrated with the ingress-nginx_ ingress controller used by Phalanx.
Incoming web requests to any Phalanx web service generate subrequests to Gafaelfawr, which then does authentication, authorization, and adjusts the HTTP headers of the request.
This integration is done via ``GafaelfawrIngress`` custom Kubernetes resources, which the Gafaelfawr Kubernetes operator converts into Ingress_ resources with the appropriate ingress-nginx-specific configuration.

.. _Gafaelfawr: https://gafaelfawr.lsst.io/
.. _Phalanx: https://phalanx.lsst.io/
.. _ingress-nginx: https://kubernetes.github.io/ingress-nginx/
.. _Ingress: https://kubernetes.io/docs/concepts/services-networking/ingress/

Development of ingress-nginx is `coming to an end <https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/>`__.
Feature development has already ceased.
After March of 2026, it will no longer receive security fixes.
Phalanx therefore must migrate to a different software stack for handling incoming requests, and Gafaelfawr must be updated to integrate with that new stack.

Additionally, the Kubernetes Ingress_ API has been frozen in favor of the new Gateway_ API, and the Kubernetes project recommends all users switch to the new API.
Since replacement of ingress-nginx will require a significant migration project, ideally the migration to the new Gateway API would be done at the same time and avoid the need for another subsequent large migration.

.. _Gateway: https://kubernetes.io/docs/concepts/services-networking/gateway/

Integration points
------------------

Gafaelfawr relies on the following integration points with ingress-nginx.
Each will have to be converted to the Gateway API and a new gateway controller or, if that is not possible, redesigned.

- Incoming web requests must first be sent to Gafaelfawr URL (the parameters of which will vary by target service) and the request must be rejected and not sent to the backend if Gafaelfawr returns failure.
- All headers in the incoming web request must be sent to Gafaelfawr.
- Gafaelfawr must be able to return its choice of status codes.
  All of 400, 401, 403, and 429 are currently returned in some situations, and more may be needed in the future.
  Gafaelfawr must be able to include a body and arbitrary headers in these responses.
  The current integration with ingress-nginx allows this but is very awkward.
- Gafaelfawr must be able to inject additional request headers that are added to the request sent to the backend after approval.
- The ingress or gateway controller handling the request must be able to cache the Gafaelfawr response for up to five minutes, but not use a cached response if the method or the ``Authorization`` or ``Cookie`` request headers have changed.
  This is used to reduce authentication traffic for services with large numbers of requests from the same user in short intervals, such as Nublado, the Portal, or the Butler server.
- Gafaelfawr must be able to inject additional response headers that are added to the response from the backend before it is sent to the user.
  This is used for rate limiting status headers and will eventually be used to comply with the IVOA authentication standard.
- Gafaelfawr must be able to remove its own cookie from any ``Cookie`` headers in the client request.

Other Phalanx applications rely on the following integration points with ingress-nginx, unrelated to Gafaelfawr.

- The Portal relies on cookie-based session affinity to consistently route a user to the same instance of the Portal.
- The Portal and the CADC TAP server rely on proxy URL rewriting to adjust the URLs returned by the backend application before returning them to the user.
- Multiple Phalanx applications rely on URL rewriting to present a different URL to the backend service than the URL the client sent.
  I believe all instances of this only remove, add, or replace a static path prefix.
- Some third-party helm charts may only provision ``Ingress`` resources and not ``Gateway``/``HTTPRoute`` resources.
  Currently, there are three 3rd-party charts we use that provision an ``Ingress``: ArgoCD, Vault, and Chronograf.
  Of these, only Chronograf does not have the option to provision ``HTTPRoute`` resources.
  We could easily write our own ``HTTPRoute`` to replace the simple ``Ingress`` that the chart provides.
  Given that, we probably don't need to support ``Ingress`` resources in the clusters at all.
  None of the Gateway API controllers will provision ``Ingress`` resources, so if we do decide we still need to support them, we will have to select an entirely different controller anyway.

Migration plan
==============

We will want to have both the ``ingress-nginx`` proxy and our chosen Gateway controller proxy active in the cluster at the same time such that apps can accept traffic from either one.
Since we use path-based routing for most of our apps, we can not control which proxy gets traffic for which app through DNS.
We need some downstream HTTP-aware proxy to route requests to the correct proxy.

There are a few ways we can do this:

* Have a third proxy in the cluster that routes to either the ingress or gateway proxies
* Have one of the ingress or gateway proxies route to the other
* Have something completely outside the cluster that does the initial routing

Any way we do this will add some overhead and complication to all requests into the cluster.
Using something completely outside of the cluster lets us keep the cluster in as close to the final state as possible.
The tradeoff is that switching traffic for an application has to happen outside of Phalanx config.

The high-level migration steps are:

#. Test promising candidates for a Gateway API implementation by installing them in a development cluster parallel to ingress-nginx using a separate external IP and testing them with hand-crafted ``Gateway`` resources.
   Muster_ exists for this purpose; its ingresses cover a wide range of expected Gafaelfawr functionality, and mobu_ can run verification tests against Muster.

   .. _Muster: https://github.com/lsst-sqre/muster
   .. _mobu: https://mobu.lsst.io/

#. Choose a Gateway API implemenation.

#. Install the Gateway API conroller, have it create a Google Cloud NLB.

#. Add support to Gafaelfawr's Kubernetes operator for generating ``Gateway`` resources and any associated resources, such as the custom middleware configuration required to send external authentication requests to the correct Gafaelfawr endpoint.
  This should use a new ``GafaelfawrGateway`` resource.

#. Add any necessary additional support to Gafaelfawr required by the chosen Gateway API implementation.
   We may also have to further optimize a hot path for Gafaelfawr authorization requests if the chosen Gateway API doesn't support caching.

#. Benchmark hot routes before updating Google Cloud load balancing infrastructure.

#. In a dev environment, say ``idfdev``, provision a Google Cloud ALB to initially route traffic 100% to the existing ``ingress-nginx``-provisioned NLB.

#. Switch ``data-dev.lsst.cloud`` to point to this new ALB.

#. Run benchmarks again, make sure we didn't lose too much performance.

#. Pick an application in the cluster, provision a ``GafaelfawrGateway`` resource.

#. Update the config of the ALB to route that application's path to the new Gateway NLB.

#. Migrate the rest of the Phalanx applications to the new implementation, refining the migration steps with each conversion.

#. Convert manually provisioned ``Ingress`` resources to ``HTTPRoute`` resources and update ALB configuration.

#. Manually provision ``HTTPRoute`` resources for any 3rd-party charts that only support ``Ingress`` resources.

#. Point ``data-dev.lsst.cloud`` at the new Gateway NLB

#. Destroy the ALB

#. Remove the ``ingress-nginx`` app from the cluster

USDF will require special attention because they currently deploy a separate ingress-nginx service outside of the vCluster_ clusters that are visible to Phalanx environment administrators.
As part of this migration, this practice should stop for Phalanx-managed clusters and the gateway API implementation should be managed by Phalanx as it is in any other Phalanx environment.

We'll also need something like the Google Cloud ALB to do path-based routing to the correct proxy.

.. _vCluster: https://www.vcluster.com/docs

Gateway API options
===================

The Kubernetes project maintains a `list of implementations <https://gateway-api.sigs.k8s.io/implementations/>`__.
Below are evaluation notes for some of the options.

Unfortunately, I have not been able to find a gateway API implementation that supports caching of external authentication results the way that ingress-nginx did.
This means none of the implementations discussed below meet our basic requirements, and we may have to find other workarounds.
See :ref:`gaps` for more details.

Based on an initial review, Envoy appears to be the best option, although this will require a significant redesign of Gafaelfawr if we want to use the GRPC protocol.
Traefik could be made to work, but we would lose the ability to inject headers into the response.
The other options I evaluated looked less interesting.

Traefik
-------

Traefik_ supports external auth via gateway middleware (``ForwardAuth``) and a Traefik-specific resource.
On failure, the full response from the external authentication provider is returned to the client, which is exactly the behavior we want.
URL rewriting is supported with middleware (``ReplacePathRegex`` and ``StripPathRegex``, among others).

.. _Traefik: https://doc.traefik.io/traefik/

Traefik interestingly has some built-in support for recognizing ingress-nginx annotations on ``Ingress`` resources and honoring them as much as Traefik is able.
Unfortunately, this support is quite limited and does not include many of the annotations we use.

Traefik appears to be missing the following necessary features:

- Traefik `does not support caching of external authentication results <https://github.com/traefik/traefik/issues/11718>`__.
- There does not appear to be a way to inject headers from the external authentication provider into the response, only into the request.
  This would mean loss of the rate limit headers on successful requests, unless we added code to every backend to mirror those headers in replies.
  It will also complicate complying with the IVOA authentication requirement to include a response header with the authenticated username.
- There does not appear to be any support for rewriting URLs returned by the backend before sending them to the client.

Envoy Gateway
-------------

The `Envoy gateway`_ is a controller that implements the Gateway protocol by dynamically configuring the `Envoy proxy`_.
If we were going to choose an Envoy-based controller, I would choose :ref:`kgateway` over Envoy Gateway, because:

* Kgateway is now a CNCF project.
  The Envoy proxy is also a CNCF project, but I don't think that includes the Envoy Gateway project.
* Kgateway seems to fix things and add features faster than Envoy Gateway.
  It took two years to `add support for allowed_client_headers_on_success <github.com/envoyproxy/gateway/issues/3787>`_ in Envoy Gateway.
  `The same feature <https://github.com/kgateway-dev/kgateway/issues/13594>`_ took 4 months in Kgateway.
* Kgateway does better on the :ref:`benchmarks`, though note the caveats with those benchmarks.

.. _Envoy proxy: https://www.envoyproxy.io/
.. _Envoy gateway: https://gateway.envoyproxy.io/docs/

External auth is configured by using the `ext_authz filter <https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter>`__.
This filter enables calling out to either an HTTP or GRPC-based auth server and manipulating the request to the backend and the response to the client based on the response from the auth server.

Both the `gRPC protocol for external auth <https://www.envoyproxy.io/docs/envoy/latest/api-v3/service/auth/v3/external_auth.proto>`__ and the `HTTP configuration <https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto#envoy-v3-api-msg-extensions-filters-http-ext-authz-v3-httpservice>`__ support almost all of the auth features we need, but the gateway API does not expose all of the necessary config.
This is not a problem with the gRPC interface because all of the necessary info is in the gRPC messages themselves, and nothing needs to be configured in the proxy.
Gafaelfawr could gain support for the gRPC protocol, and in some ways it would be an improvement over the way external auth is currently handled.
For example, only one endpoint would be required, since all of the necessary information is in the request body.
Gafaelfawr could maintain its own internal database of authorization rules, based on gathered Kubernetes resources, avoiding the need to create a separate external auth rule for every ingress or gateway.
This would require a substantial redesign of Gafaelfawr's request flow, however.

.. list-table:: HTTP auth proxy support
   :header-rows: 1

   * - Feature
     - Proxy Support
     - Gateway Support
   * - Denied: response code
     - yes
     - yes
   * - Denied: body
     - yes
     - yes
   * - Denied: headers to client
     - yes
     - yes [#]_
   * - Accepted: headers to backend
     - yes
     - yes
   * - Accepted: headers to client
     - yes
     - yes
   * - Redirect to login
     - **no**
     - **no** [#]_
   * - Cache auth responses
     - **no**
     - yes
   * - Remove Gafaelfawr cookie
     - **no**
     - **no**
   * - Session affinity
     - yes
     - yes

.. [#] Though the whole header passing API in the gateway is currently pretty buggy, as seen in `this GitHub issue <https://github.com/envoyproxy/envoy/issues/41828#issuecomment-3766420747>`__
.. [#] Gafaelfawr would have to return a 3xx response with the correct location

One other way The HTTP option is incompatible with Gafaelfawr is that it always appends the path of the request to the auth server path.
For example, if the client request is to ``/somepath``, and the auth proxy is configured to request ``/authpath?foo=bar``, then the actual auth server path requested is ``/authpath?foo=bar/somepath``.
We would likely be able to disable this path appending soon, based on `this GitHub issue <https://github.com/envoyproxy/envoy/issues/43398>`__ and associated PR.

Envoy supports URL rewriting via the standardized ``HTTPURLRewriteFilter`` approach, which is cleaner than Traefik's use of custom middleware.
This approach is more limited in what it can do, but I believe it will satisfy our requirements.

Envoy appears to be missing the following necessary features:

- Envoy `does not support caching of external authentication results <https://github.com/envoyproxy/envoy/issues/3023>`__.
- There does not appear to be any support for rewriting URLs returned by the backend before sending them to the client.
  We may be able to use `a custom Lua extension <https://gateway.envoyproxy.io/docs/tasks/extensibility/lua/>`__ for this.
- The Envoy Gateway HTTP ext auth feature does not allow us to ex

Unlike some of the other new gateways, Envoy is written in C++, rather than in a memory-safe language such as Go.
This is not as bad as being written in C, but it somewhat increases the risk of security vulnerabilities.

According to :ref:`benchmarks`, Envoy Gateway is prone to interruptions when updating routes.

.. _agentgateway:

Agentgateway
------------

Agentgateway_ is the newest Gateway API controller on this list.
It is managed by the same folks that currently manage :ref:`kgateway`.
It started as a bunch of AI-specfic features on top of Kgateway, but it has evolved into a completely standalone controller with its own custom proxy written in Rust.
It has a ton of AI related features that we don't need, but it has almost all of the features that we do need. A brand new proxy written in a memory-safe language is great, but it is also a bit scary to adopt something that has seen little real-world testing into such a security-critical and commonly vulnerable place in our architecture.

It is an accepted project of the the `Agentic AI Foundation`_ (AAIF), which is an "open foundation under the Linux Foundation that hosts open protocols and open source projects for agentic AI, including the Model Context Protocol (MCP), goose, AGENTS.md, Agent2Agent (A2A) and agentgateway."
This maybe makes it less likely to be abandoned in the future, though the AAIF is focused on AI/Agentic functionality, rather than general Kubernetes functionality like the CNCF.

It is one of two gateway controllers that support external auth response caching (:ref:`nginx-gateway` is the other).
It does support filtering the Gafaelfawr cookie from the upstream request, but it requires using a `CEL expression`_ to directly manipulate the cookie header, which is a bit scary.

One big difference between the Agentgateway proxy and NGINX is that the Agentgateway proxy does not buffer requests to disk.
It either streams them entirely, or buffers them in memory.
The only way we can set a limit is if we configure memory buffering with a limit.
Our current `ingress-nginx` 2GB request buffering limit would be too big to buffer entirely in memory.

.. list-table:: Agentgateway differentiating features support
   :header-rows: 1

   * - Feature
     - Support
   * - External auth
     - yes, but auth request uses the incoming request method, not just GET
   * - Redirect to login
     - yes
   * - Cache auth responses
     - yes, but it will cache them all, we can't filter by status code
   * - Remove Gafaelfawr cookie from request to upstream
     - yes, with a CEL expression
   * - Session affinity
     - yes, but it doesn't set its own cookie, it hashes something already in the request, like the gafaelfawr cookie
   * - Limit request body to 2GB
     - **no**
   * - Rewrite redirect Location's
     - yes
   * - Rewrite `Server` header
     - yes

.. _Agentgateway: https://agentgateway.dev
.. _Agentic AI Foundation: https://aaif.io
.. _CEL expression: https://agentgateway.dev/docs/standalone/latest/reference/cel/


.. _kgateway:

Kgateway
--------

Kgateway_ was a wrapper around Envoy with a lot of tacked-on AI marketing buzzwords.
It is still a wrapper around Envoy, but the AI marketing buzzword implementation has moved to :ref:`agentgateway`.

Kgateway has been accepted into the `Cloud Native Computing Foundation`_ (CNCF), which is a part of the `Linux Foundation`.
This maybe makes it less likely to be abandoned in the future.

Its HTTP external auth implementation is more configurable than Envoy Gateway's, but some things we need are still only possible with the gRPC external auth interface.

Like the Agentgateway proxy, one big difference between the Envoy proxy and NGINX is that the Envoy proxy does not buffer requests to disk.
It either streams them entirely, or buffers them in memory.

.. list-table:: Kgateway differentiating features support
   :header-rows: 1

   * - Feature
     - Support
   * - External auth
     - yes, but auth request uses the incoming request method, not just GET
   * - Redirect to login
     - **no** - but it would return a 301 from Gafaelfawr to the downstream
   * - Cache auth responses
     - **no**
   * - Remove Gafaelfawr cookie from request to upstream
     - **no**, only with gRPC external auth
   * - Session affinity
     - yes
   * - Limit request body to 2GB
     - **no**
   * - Rewrite redirect Location's
     - almost, it may send an empty ``Location`` header on responses that don't have one. It happens via a jinja-like templating language embedded in a ``TrafficPolicy``.
   * - Rewrite `Server` header
     - yes


.. _Cloud Native Computing Foundation: https://www.cncf.io/projects/kgateway/
.. _Kgateway: https://kgateway.dev/docs/envoy/latest/about/overview/

It does well in the Gateway controller benchmarks, but remember those are produced by the makers of Kgateway.

The documentation is quite nice and easy to follow, though, so it may be worth a closer look.

.. _Linux Foundation: https://www.linuxfoundation.org

.. _nginx-gateway:

NGINX Gateway Fabric
--------------------

`NGINX Gateway Fabric`_ is the NGINX-driven Gateway API implementation maintained by the NGINX maintainers themselves.
It therefore in theory would support everything that we are currently doing with ingress-nginx, since the full capabilities of NGINX are available.

.. _NGINX Gateway Fabric: https://docs.nginx.com/nginx-gateway-fabric

Unfortunately, very few of the features that we need appear to be supported out of the box.
Unlike ingress-nginx, which provided simple annotation-driven configuration to enable NGINX features, it looks like using NGINX Gateway Fabric would require we write and maintain most of the low-level NGINX configuration ourselves and inject it with their ``SnippetsFilter`` API.
Given the complexity of NGINX configuration, this is rather unappealing.

So far as I can tell, this includes all support for external auth.
There does not appear to be any native support for setting it up, so the full backend configuration and ``auth_request`` block would have to be written directly in the NGINX configuration language and injected via ``SnippetsFilter``.

NGINX is written in C and does not have a great security track record.
Ideally, this replacement project would let us migrate away from an ingress or gateway written in a memory-unsafe language prone to security issues.

Among Agentgateway, Kgateway, and NGINX Gateway Fabric, this is the support for the differentiating features, with the caveat above that many of these would need to be implenented with raw config snippets:

.. list-table:: NGINX Gateway Fabric differentiating features support
   :header-rows: 1

   * - Feature
     - Support
   * - External auth
     - yes
   * - Redirect to login
     - yes
   * - Cache auth responses
     - yes
   * - Remove Gafaelfawr cookie from request to upstream
     - yes
   * - Session affinity
     - yes
   * - Limit request body to 2GB
     - yes
   * - Rewrite redirect Location's
     - yes
   * - Rewrite `Server` header
     - **no**

.. _haproxy:

HAProxy
-------

HAProxy_ has an initial implementation of the Kubernetes Gateway API, but it is appears to be incomplete, largely undocumented, and possibly unmaintained.
I was unable to determine whether it supported any of the features we need.

.. _HAProxy: https://www.haproxy.com/documentation/kubernetes-ingress/gateway-api/

.. _benchmarks:

Benchmarks
==========

Some folks have done some `Gateway API controller benchmarks`_ that compare some of the controllers we are considering.
These are interesting, but come with some large caveats:

* They are almost a year out of date at the time of this writing.
  Someone else (not the orignal developer) has forked the original repo and generated some `updated benchmarks`_.
* The original benchmarks were done by a https://solo.io employee, the company behind Agentgateway, Kgateway, and Istio at the time the benchmarks were published, all of which appear in the benchmarks.
  This is prominently disclaimed in the benchmark write-up.
* They do not focus on traffic performance, like throughput/latency through the proxy for different kinds of client requests.

Even with these caveats, I think they are still worth looking at when we make our choice.
The error benchmarks are especially relevant.

.. _Gateway API controller benchmarks: https://github.com/howardjohn/gateway-api-bench
.. _updated benchmarks: https://github.com/NoOverflow/gateway-api-bench/blob/main/README-v3.md

.. _gaps:

External authentication caching
===============================

Nublado, the Portal, and the Butler server rely on caching of external authentication responses from Gafaelfawr for up to five minutes.
Without this support, every resource request to those services requires a request to Gafaelfawr, which can mean rather high load on Gafaelfawr and on the gateway given the number of resource requests.
For Nublado and Portal, this means an extra request for every JavaScript AJAX request.
For Butler, uncached authorization checks caused noticable performance degredation for common use cases before caching was enabled.

If we choose a Gateway API controller without auth response caching support, we could attempt to optimize the Gafaelfawr request rather than avoid it.
Currently, every authorization check requires a call to Redis.
That call, at least, could be avoided by adding an additional in-memory cache similar to that used in ingress-nginx currently, using the method and the ``Authorization`` and ``Cookie`` headers as keys.
It's not clear whether that would be sufficient to make an approach without gateway-side caching viable, since each request would still have to pay the cost of parsing the Gafaelfawr request in Python.

We could use a Gateway API controller that allows us to use gRPC for the external auth request.
We would have to experiment to see if those requests were more efficient; they might be, since the parsing of the request is done via protobuf and should be faster than the Python-based parsing of conventional HTTP query parameters.

In the most extreme case, it may be possible to implement a caching layer for the external authorization check in another, faster programming language (Rust or Go) with gRPC support, and have it call out to the Gafaelfawr Python backend only when needed.
This is a lot of additional complexity, however, and should only be considered if the lack of caching causes unacceptable performance degredation and we can't find a better alternative.

It is possible to set up a cache between the gateway and Gafaelfawr, via a separate `Vinyl cache`_ instance or something similar, but this is very unappealing from a complexity standpoint.
Performance of a Vinyl cache as a sidecar container in the Gafaelfawr pod seems very close to a native NGINX cache, despite the extra network hop involved.
There is a slightly odd pattern in the data where requests-per-second goes higher and lower every ~60s, but this pattern is present in the no-cache tests too.
You can see this in graphs of metrics over time by opening the files in the ``auth-cache-test-results/2026-03-16-120408-40-users-600s-duration`` directory in a browser.

These are data from 40 simulated users hitting `Muster`_ endpoints as fast as they can for 10 minutes: ("vus" is virtual users):

.. code-block::
   :caption: No auth cache

    EXECUTION
    iteration_duration.............: avg=149.04ms min=29.83ms med=137.41ms max=876.41ms p(90)=196.48ms p(95)=204.26ms
    iterations.....................: 161010 268.292831/s
    vus............................: 40     min=40          max=40
    vus_max........................: 40     min=40          max=40

.. code-block::
   :caption: Vinyl cache

    EXECUTION
    iteration_duration.............: avg=66.17ms  min=21.32ms med=43.13ms max=1.46s    p(90)=100.17ms p(95)=104.54ms
    iterations.....................: 362524 604.174278/s
    vus............................: 40     min=40          max=40
    vus_max........................: 40     min=40          max=40

.. code-block::
   :caption: NGINX cache

    EXECUTION
    iteration_duration.............: avg=65.42ms  min=19.91ms med=42.25ms max=1.21s    p(90)=100.01ms p(95)=104.17ms
    iterations.....................: 366684 611.103082/s
    vus............................: 40     min=40          max=40
    vus_max........................: 40     min=40          max=40

.. _Vinyl cache: https://vinyl-cache.org/

Migrate to another Ingress controller
=====================================

Another option is to migrate to another Ingress-based controller that will remain supported, instead of going all the way to a Gateway-based controller.
Even though the Ingress API has been frozen, there are no plans to deprecate or remove it.
If it is significantly easier, we may want to migrate to another Ingress-based controller first so we can at least be using something that is still getting security patches.

NGINX Ingress
-------------

The `NGINX Ingress`_ controller is the official NGINX ingress controller maintained by F5, the owners of NGINX.
It theoretically supports all of the functionality of ingress-nginx because it too uses NGINX as the proxy.

.. _NGINX Ingress: https://docs.nginx.com/nginx-ingress-controller/

Unfortunately, it has the same problem as the :ref:`nginx-gateway`: very few of the features that we need appear to be supported out of the box.
We would be required to write and maintain explicit NGINX configuration ourselves.

.. _ai-conversion-table:

ingress-nginx annotation conversions
====================================

Below is a table of how every ``ingress-nginx`` annotation we have in our ``idfprod`` cluster (as of early October, 2026) and every ``ingress-nginx`` config snippet option maps to features in :ref:`agentgateway`, :ref:`kgateway`, and :ref:`nginx-gateway`.
This table was created with heavy LLM assistance.
I (Dan Fuchs) have not verified every cell in this table, but I have verified the things that I refer to in each specific Gateway API controller section above.
Now begin the robots' words:

Comparison of ingress-nginx settings with kgateway 2.4.7, agentgateway 1.7.0,
and NGINX Gateway Fabric (NGF) 2.8.0.
"Native" refers to Gateway API or controller-policy support, not support for
the ingress-nginx annotation itself. Features marked "partial" or "snippet"
are not exact portable equivalents.

External authentication
-----------------------

.. list-table:: External authentication
   :header-rows: 1
   :widths: 22 26 26 26

   * - ingress-nginx feature / setting
     - kgateway 2.4.7
     - agentgateway 1.7.0
     - NGF 2.8.0
   * - ``auth-url``
     - **Native HTTP ext auth:** ``TrafficPolicy.extAuth`` plus ``GatewayExtension.extAuth.httpService``.
     - **Native:** ``AgentgatewayPolicy.traffic.extAuth.http``.
     - **Native:** experimental Gateway API ``HTTPRoute`` ``ExternalAuth`` filter.
   * - Auth URL path and query parameters
     - ``httpService.pathPrefix`` prepends to the original URI, not an exact arbitrary URL override. Verify Gafaelfawr query parameters.
     - ``http.path`` CEL can construct the auth path and query.
     - ``externalAuth.http.path`` supplies a fixed auth path; query-string equivalence needs verification.
   * - ``auth-method: GET``
     - No exposed exact HTTP ext-auth method override; typically forwards the original request method.
     - No exposed HTTP ext-auth method override; uses original method.
     - Internal auth subrequest generally uses GET, but verify the generated NGINX configuration and forwarded Method header.
   * - Forward Cookie and Authorization to auth server
     - Explicitly include ``cookie`` in ``GatewayExtension.extAuth.headersToForward``.
     - ``http.allowedRequestHeaders``; configure both headers.
     - ``externalAuth.http.allowedHeaders``.
   * - ``auth-response-headers`` to backend
     - **Native:** ``authorizationResponse.headersToBackend``.
     - **Native:** ``http.allowedResponseHeaders``.
     - **Native:** ``http.allowedResponseHeaders``.
   * - Auth denial headers to client
     - **Native:** ``authorizationResponse.headersToClient``.
     - Denied HTTP response headers can be passed to the client.
     - ``WWW-Authenticate`` on 401; arbitrary denial headers need custom handling.
   * - Auth denial body to client
     - **Native:** denied response body.
     - **Native:** can preserve denied HTTP response body.
     - Generated NGINX error body by default; custom error handling for exact matching.
   * - Auth success headers to client
     - **Native:** ``authorizationResponse.headersToClientOnSuccess``.
     - No dedicated direct mapping; ``responseMetadata`` and response transformation may work.
     - No native ExternalAuth success-response-to-client mapping; needs custom handling.
   * - ``auth-signin``
     - No direct equivalent; auth service can issue a redirect with ``Location`` forwarded.
     - **Native:** ``http.redirect`` for 401/403; responds with 302.
     - ``error_page`` or redirect snippet; outside the standard ExternalAuth filter.
   * - ``auth-cache-key``
     - No native HTTP external-auth cache.
     - **Native:** ``cache.key`` is an ordered list of CEL expressions.
     - ``proxy_cache_key`` via snippets, in the auth subrequest context.
   * - ``auth-cache-duration: 200 202 401 5m``
     - No native HTTP external-auth cache.
     - **Partial:** ``ttl: 5m`` caches successful 2xx and 401/403, not exactly 200/202/401.
     - **Via snippets:** ``proxy_cache_valid 200 202 401 5m``.
   * - Skip cache unless Cookie AND Authorization are present
     - Requires external/custom cache.
     - **Yes:** direct ``request.headers["cookie"]`` and ``request.headers["authorization"]`` CEL key expressions bypass cache on absent header.
     - **Yes:** ``proxy_cache_bypass`` and ``proxy_no_cache`` conditions.
   * - Auth service unavailable / failure mode
     - ``failOpen`` and ``statusOnError``.
     - ``failureMode: FailOpen`` or ``FailClosed``.
     - NGINX ``auth_request`` generally fails closed; custom error handling via snippets.

Routing, rewrites, headers, and cookies
---------------------------------------

.. list-table:: Routing, rewrites, headers, and cookies
   :header-rows: 1
   :widths: 22 26 26 26

   * - ingress-nginx feature / setting
     - kgateway 2.4.7
     - agentgateway 1.7.0
     - NGF 2.8.0
   * - ``use-regex: "true"``
     - **Native:** ``HTTPRoute`` ``RegularExpression`` path match.
     - **Native:** regex path match.
     - **Native:** regex path match; generated NGINX ``~`` matching can differ in case sensitivity from ingress-nginx ``~*``.
   * - ``rewrite-target`` with ``$1``/``$2`` captures
     - **Native:** ``TrafficPolicy.urlRewrite.pathRegex``.
     - **Native:** CEL/regex path rewrite.
     - **Snippet:** NGINX ``rewrite`` with captures; Gateway API ``URLRewrite`` has no regex capture substitution.
   * - ``proxy-redirect-from``
     - **Supported via** ``TrafficPolicy.transformation.response.set``: match
       a prefix of the upstream ``Location`` and replace it. Unlike NGINX
       ``proxy_redirect``, a missing ``Location`` may produce an empty header;
       test before relying on exact equivalence.
     - **Supported via** ``AgentgatewayPolicy.traffic.transformation.response.set``:
       CEL can conditionally replace an upstream ``Location`` prefix. A missing
       header makes the CEL lookup fail; agentgateway removes/omits ``Location``
       rather than setting it to an empty string.
     - **Snippet:** ``proxy_redirect FROM TO``.
   * - ``proxy-redirect-to``
     - Same kgateway response transformation, providing the replacement prefix;
       the missing-``Location`` caveat still applies. Also does not reproduce
       NGINX ``Refresh`` rewriting automatically.
     - Same CEL response transformation, with the replacement prefix; no
       empty-``Location`` caveat on absent headers. A CEL error for another
       reason also removes ``Location``.
     - **Snippet:** same ``proxy_redirect`` directive.
   * - ``ssl-redirect: "true"``
     - **Native:** ``HTTPRoute.RequestRedirect`` to HTTPS, 308.
     - **Native:** ``HTTPRoute.RequestRedirect`` to HTTPS, 308.
     - **Native:** same Gateway API filter.
   * - ``affinity: cookie``
     - **Native:** experimental Gateway API ``sessionPersistence`` with ``Cookie``; issues its own persistence cookie.
     - **Partial:** ``backend.sessionAffinity.source`` hashes an existing request attribute or cookie; does not issue a cookie.
     - **Native (NGINX OSS in 2.8):** experimental ``sessionPersistence`` with ``Cookie``; issues a cookie.
   * - ``session-cookie-path: /portal/app``
     - No exact exposed cookie-Path route policy; inspect resulting ``Set-Cookie``.
     - Not applicable: agentgateway does not issue an affinity cookie.
     - **Partial:** Path derived from route match; regex Portal routes need testing or refactoring.
   * - ``session-cookie-change-on-failure: "true"``
     - Healthy endpoint failover exists but does not exactly reproduce replacement-cookie behavior.
     - Hashing remaps on endpoint changes; no managed replacement cookie.
     - Persistence/failover exists; no exact exposed ingress-nginx switch.
   * - ``proxy-cookie-path: /suit /portal/app``
     - No native per-cookie ``Path`` rewrite; custom response processing.
     - CEL response transform possible; repeated ``Set-Cookie`` fields require careful handling.
     - **Snippet:** ``proxy_cookie_path /suit /portal/app``.
   * - ``configuration-snippet`` (general)
     - No raw NGINX snippets; use policies, routes, or ExtProc.
     - No raw NGINX snippets; use CEL policies or ExtProc.
     - **Supported escape hatch:** route-level ``SnippetsFilter``.
   * - ``proxy_set_header X-Original-URI $request_uri``
     - Header transformation; preserve original URI before rewrites.
     - CEL request-header transformation using original URI.
     - Header modifier can expand NGINX variables, or use snippet.
   * - ``proxy_set_header X-Forwarded-Proto https``
     - Request-header modifier and trusted-proxy configuration.
     - Request-header modifier or CEL.
     - Request-header modifier or snippet.
   * - ``proxy_set_header X-Forwarded-Port 443``
     - Request-header modifier.
     - Request-header modifier.
     - Request-header modifier or snippet.
   * - ``proxy_set_header X-Forwarded-Path /portal/app``
     - Request-header modifier.
     - Request-header modifier.
     - Request-header modifier or snippet.
   * - ``more_set_headers "server: OpenCADC/cadc-rest"``
     - **Supported:** configure Gateway-level
       ``ListenerPolicy.default.httpSettings.serverHeaderTransformation: PassThrough``
       and set ``Server: OpenCADC/cadc-rest`` on selected ``HTTPRoute`` resources using
       ``ResponseHeaderModifier``. Alternatively, use ``Overwrite`` and
       ``serverName`` on the ListenerPolicy for a Gateway-wide value. Envoy
       otherwise overwrites ``Server`` by default; test this combination.
     - **Supported natively:** route-level ``ResponseHeaderModifier`` or
       ``AgentgatewayPolicy.traffic.headerModifiers.response.set`` with
       ``Server: OpenCADC/cadc-rest``. No special listener configuration and
       no CEL needed for a constant; a later transformation can still override it.
     - ``ResponseHeaderModifier`` forbids ``Server``; requires NGINX-specific processing.

Per-Ingress timeouts, request bodies, and buffering
---------------------------------------------------

.. list-table:: Per-Ingress timeouts, request bodies, and buffering
   :header-rows: 1
   :widths: 22 26 26 26

   * - ingress-nginx feature / setting
     - kgateway 2.4.7
     - agentgateway 1.7.0
     - NGF 2.8.0
   * - ``proxy-connect-timeout`` (900, 1800)
     - Backend connect-timeout setting; comparable.
     - ``backend.tcp.connectTimeout``; comparable.
     - **Exact NGINX directive:** ``ProxySettingsPolicy.timeout.connect``.
   * - ``proxy-read-timeout`` (300, 900, 1800)
     - Upstream stream/response timeout, but not identical idle-read semantics.
     - ``traffic.timeouts.responseIdle`` and backend HTTP timeout; not identical.
     - **Exact:** ``ProxySettingsPolicy.timeout.read``.
   * - ``proxy-send-timeout`` (300, 900, 1800)
     - No exposed independent NGINX-style upstream-write idle timeout.
     - No equivalent independent upstream-write idle timeout.
     - **Exact:** ``ProxySettingsPolicy.timeout.send``.
   * - ``proxy-body-size: 0m`` (unlimited)
     - Omit request-body limit; avoid buffering entire body solely for size enforcement.
     - **Equivalent for streamed requests by default:** there is no general
       request-body size cap on the ordinary proxy path. Do not enable
       ``traffic.buffer.request`` to emulate unlimited uploads: buffering and
       body-inspection/ExtProc policies have their own size/memory limits.
     - **Exact:** ``ClientSettingsPolicy.body.maxSize: "0"``.
   * - ``proxy-buffer-size: 24k`` (Portal admin)
     - No exact per-route initial upstream-header buffer setting.
     - No exact upstream-header buffer setting.
     - **Exact:** ``ProxySettingsPolicy.buffering.bufferSize: "24k"``.
   * - ``client-header-buffer-size: 24k``
     - No migration required: unsupported/inert ingress-nginx Ingress annotation.
     - Same.
     - Same.
   * - Request buffering
     - No NGINX-style on-disk temporary-file buffering; filters can buffer in memory.
     - Streams by default; explicit body buffering/inspection consumes memory.
     - Native NGINX buffering and temporary files.

Global ingress-nginx ConfigMap defaults
---------------------------------------

.. list-table:: Global ingress-nginx ConfigMap defaults
   :header-rows: 1
   :widths: 22 26 26 26

   * - ingress-nginx feature / setting
     - kgateway 2.4.7
     - agentgateway 1.7.0
     - NGF 2.8.0
   * - ``proxy-body-size: 2g``
     - No equivalent low-memory streaming cap via ``TrafficPolicy.buffer.maxRequestSize``; it buffers.
     - No corresponding general 2 GiB streaming cap; ``traffic.buffer`` buffers bodies.
     - **Native:** ``ClientSettingsPolicy.body.maxSize: "2g"``.
   * - ``proxy-buffer-size: 64k``
     - Different Envoy response-header/buffering controls; no exact route equivalent.
     - No exact equivalent.
     - **Native:** ``ProxySettingsPolicy.buffering.bufferSize: "64k"``.
   * - ``proxy-busy-buffers-size: 64k``
     - No exact equivalent.
     - No exact equivalent.
     - Field exists but validation requires busyBuffersSize > bufferSize; your equal 64k settings need adjustment or tested snippet.
   * - ``large-client-header-buffers: 4 64k``
     - Aggregate header-size limits (``ListenerPolicy.httpSettings.maxRequestHeadersKb``), not exact NGINX semantics.
     - Frontend limits do not expose the exact NGINX 4 x 64k setting.
     - **Snippet:** ``large_client_header_buffers 4 64k``.
   * - ``compute-full-forwarded-for: "true"``
     - Envoy XFF append and trusted-hop handling; verify behavior.
     - Header/CEL transformations; no exact trusted-hop policy.
     - ``$proxy_add_x_forwarded_for``; inspect NGINX RealIP effects.
   * - ``use-forwarded-headers: "true"``
     - Configure trusted-proxy and original scheme/host handling.
     - **No direct ingress-nginx equivalent needed behind a passthrough GKE
       L4 NLB** when agentgateway terminates TLS: derive scheme/client IP from
       the connection and original host from ``Host``/``:authority``; treat
       incoming ``X-Forwarded-*`` and ``Forwarded`` as untrusted. Optionally
       overwrite/remove them with a ``PreRouting`` policy. Preserve peer IP
       with Service ``externalTrafficPolicy: Local``. An upstream HTTP proxy
       needs explicit trusted-source validation; agentgateway does not expose
       ingress-nginx-style trusted-hop/CIDR configuration.
     - NGINX RealIP trust and forwarding header overrides, if needed.
   * - ``ssl-redirect: "true"``
     - HTTPS redirect ``HTTPRoute.RequestRedirect``.
     - Same.
     - Same.
   * - ``error-log-level: error``
     - Envoy logging via ``GatewayParameters``.
     - Proxy logging via ``AgentgatewayParameters``.
     - ``NginxProxy.logging.errorLevel: error``.
   * - ``allow-snippet-annotations: "true"``
     - Not applicable: no snippets.
     - Not applicable: no NGINX snippets.
     - Enable ``nginxGateway.snippets.enable=true`` in Helm.
   * - ``annotations-risk-level: Critical``
     - Not applicable.
     - Not applicable.
     - No direct risk-level setting; restrict snippet editing with RBAC.
   * - ``server-snippet``
     - No arbitrary NGINX server block.
     - No arbitrary NGINX server block.
     - ``SnippetsPolicy`` with suitable server context.
   * - ``proxy-buffering`` (default off)
     - Envoy streaming model; no direct toggle.
     - Streams without explicit response buffering.
     - Use ``ProxySettingsPolicy.buffering.disable: true`` to preserve default.
   * - ``proxy-request-buffering`` (default on)
     - Different buffering architecture.
     - Different buffering architecture.
     - NGINX request buffering; check generated directive/default.

External-auth snippets and custom error responses
-------------------------------------------------

.. list-table:: External-auth snippets and custom error responses
   :header-rows: 1
   :widths: 22 26 26 26

   * - ingress-nginx feature / setting
     - kgateway 2.4.7
     - agentgateway 1.7.0
     - NGF 2.8.0
   * - ``auth_request_set $auth_error_body $upstream_http_x_error_body``
     - No NGINX variable; can forward selected auth denial headers/body.
     - Denied auth response can preserve body/headers; no identical variable assignment.
     - **Snippet:** ``auth_request_set``.
   * - ``auth_request_set`` for ``X-Error-Status``
     - Forward relevant denial header; further transformation may be needed.
     - Auth denial headers are returned with denial response.
     - **Snippet:** ``auth_request_set``.
   * - ``auth_request_set`` for ``Retry-After`` and ``WWW-Authenticate``
     - ``authorizationResponse.headersToClient``.
     - Denial HTTP response headers.
     - ``WWW-Authenticate`` on 401; other headers through snippets.
   * - ``auth_request_set`` for ``X-RateLimit-*``
     - Forward via ``authorizationResponse`` to backend or client.
     - Response metadata plus transformations; not a simple success-to-client mapping.
     - **Snippet:** capture headers; ``add_header ... always`` or equivalent.
   * - ``more_set_headers`` for rate-limit headers
     - Response modifiers/auth-response header forwarding.
     - CEL response transformation.
     - ``add_header`` or njs; headers-more not included by default.
   * - ``error_page 403 = @autherror``
     - No named-location equivalent; customize denied response or auth service.
     - No named-location equivalent; can preserve denial response from auth service.
     - **Snippet:** NGINX ``error_page`` and named location.
   * - ``server-snippet`` defining ``@autherror``
     - No NGINX server context.
     - No NGINX server context.
     - **Snippet:** ``SnippetsPolicy`` server context; test generated location compatibility.
   * - Remove only Gafaelfawr cookie before backend
     - Custom Cookie rewriting; removing whole Cookie is not equivalent.
     - CEL-based Cookie parse/rebuild; avoid dropping unrelated cookies.
     - NGINX map/njs or custom snippet.
   * - Remove Authorization before backend
     - **Native:** request-header removal.
     - **Native:** ``traffic.headerModifiers`` or CEL transformation.
     - **Native:** ``RequestHeaderModifier``.
   * - Remove empty Cookie request headers
     - Conditional processing.
     - CEL conditional transformation.
     - NGINX map/snippet or equivalent.

Implementation notes and clarifications
-------------------------------------

``proxy-redirect-from`` and ``proxy-redirect-to`` are not absent from either
kgateway or agentgateway. Both can perform the upstream ``Location`` prefix
rewrite (for example, ``/suit/login`` to ``/portal/app/login``) without
changing the backend. Their behavior differs when ``Location`` is missing:

* **kgateway 2.4.7:** a ``TrafficPolicy`` response template can compute the
  replacement, but ``transformation.response.set`` unconditionally sets the
  named header. Test whether a response lacking ``Location`` gets
  ``Location:`` with an empty value. Unlike the NGINX directive, the response
  transformation does not automatically rewrite ``Refresh`` headers.
* **agentgateway 1.7.0:** a CEL response transformation can reference
  ``response.headers["location"]`` and only replace values that begin with
  ``/suit/``. If the header is absent, CEL evaluation fails and the
  implementation removes ``Location`` rather than generating an empty value.
  Other CEL evaluation failures remove the header too. Later response policies
  can still modify the result.

For the custom ``Server: OpenCADC/cadc-rest`` response header:

* **kgateway 2.4.7:** setting ``Server`` on an HTTPRoute alone is not sufficient
  with Envoy's default header behavior. Set the Gateway's
  ``ListenerPolicy.default.httpSettings.serverHeaderTransformation`` to
  ``PassThrough``, then apply an ``HTTPRoute`` ``ResponseHeaderModifier`` only
  to CADC TAP routes. This changes how other routes handle upstream ``Server``
  headers. If every route should have this name, use ListenerPolicy
  ``serverHeaderTransformation: Overwrite`` with
  ``serverName: OpenCADC/cadc-rest`` instead.

Agentgateway's unbuffered HTTP request path has no general request-body size
cap equivalent to ``client_max_body_size``. Therefore ``proxy-body-size: 0m``
needs no body-limit policy on normal streamed traffic. By contrast, its
body-buffering and body-inspection policies impose separate limits and memory
requirements. This does **not** reproduce your global ``2g`` cap: streamed
requests larger than 2 GiB are not automatically rejected.

References
----------

* `kgateway 2.4.7 release <https://github.com/kgateway-dev/kgateway/releases/tag/v2.4.7>`_
* `agentgateway 1.7.0 release <https://github.com/agentgateway/agentgateway/releases/tag/v1.7.0>`_
* `NGF 2.8.0 release <https://github.com/nginx/nginx-gateway-fabric/releases/tag/v2.8.0>`_
* `NGF session persistence <https://docs.nginx.com/nginx-gateway-fabric/traffic-management/session-persistence/>`_
* `kgateway API reference <https://kgateway.dev/docs/envoy/latest/reference/api/>`_
* `agentgateway API reference <https://agentgateway.dev/docs/kubernetes/latest/reference/api/>`_
* `NGF API reference <https://docs.nginx.com/nginx-gateway-fabric/reference/api/>`_
* `kgateway ListenerPolicy API <https://kgateway.dev/docs/envoy/latest/reference/api/>`_
* `kgateway response-header control <https://kgateway.dev/docs/envoy/latest/traffic-management/header-control/response-header/>`_
* `agentgateway response-transform implementation (v1.7.0) <https://github.com/agentgateway/agentgateway/blob/v1.7.0/crates/agentgateway/src/http/transformation_cel.rs>`_
* `agentgateway header mutation implementation (v1.7.0) <https://github.com/agentgateway/agentgateway/blob/v1.7.0/crates/agentgateway/src/http/mod.rs>`_
* `agentgateway response processing order (v1.7.0) <https://github.com/agentgateway/agentgateway/blob/v1.7.0/crates/agentgateway/src/proxy/httpproxy.rs>`_
* `agentgateway response header modifier implementation (v1.7.0) <https://github.com/agentgateway/agentgateway/blob/v1.7.0/crates/agentgateway/src/http/filters.rs>`_
* `agentgateway controller header modifier translation (v1.7.0) <https://github.com/agentgateway/agentgateway/blob/v1.7.0/controller/pkg/agentgateway/plugins/traffic_plugin.go>`_
