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

Other Phalanx applications rely on the following integration points with ingress-nginx, unrelated to Gafaelfawr.

- The Portal relies on cookie-based session affinity to consistently route a user to the same instance of the Portal.
- The Portal and the CADC TAP server rely on proxy URL rewriting to adjust the URLs returned by the backend application before returning them to the user.
- Multiple Phalanx applications rely on URL rewriting to present a different URL to the backend service than the URL the client sent.
  I believe all instances of this only remove, add, or replace a static path prefix.
- Some third-party applications may only support ``Ingress`` resources and not ``Gateway`` resources.
  Any ingress-nginx replacement should therefore be able to serve ``Ingress`` resources, but does not need to support Gafaelfawr integration with an ``Ingress``.

Migration plan
==============

The high-level migration steps are:

#. Test promising candidates for a Gateway API implementation by installing them in a development cluster parallel to ingress-nginx using a separate external IP and testing them with hand-crafted ``Gateway`` resources.
   Muster_ exists for this purpose; its ingresses cover a wide range of expected Gafaelfawr functionality, and mobu_ can run verification tests against Muster.

   .. _Muster: https://github.com/lsst-sqre/muster
   .. _mobu: https://mobu.lsst.io/

#. Choose a Gateway API implemenation.

#. Add support to Gafaelfawr's Kubernetes operator for generating ``Gateway`` resources and any associated resources, such as the custom middleware configuration required to send external authentication requests to the correct Gafaelfawr endpoint.
   Initially, this should accept ``GafaelfawrIngress`` resources, if possible, and transform them into equivalent ``Gateway`` resources.
   This will probably require adding a new field to ``GafaelfawrIngress`` to select the type of resource to generate so that we can enable this one-by-one.
   If that proves too complex, we can go directly to a new ``GafaelfawrGateway`` resource and corresponding Gafaelfawr implementation.

#. Add any necessary additional support to Gafaelfawr required by the chosen Gateway API implementation.
   We may also have to further optimize a hot path for Gafaelfawr authorization requests if the chosen Gateway API doesn't support caching.

#. Add Phalanx support for choosing between ingress-nginx and the new Gateway API, and write migration steps for how to convert an existing cluster.

#. Migrate Phalanx environments to the new implementation, refining the migration steps with each conversion.

#. Add Gafaelfawr support for a new ``GafaelfawrGateway`` resource, if that was not required earlier.

#. Convert all ``GafaelfawrIngress`` resources in Phalanx to ``GafaelfawrGateway``.
   Also convert as many third-party chart ingresses to gateways as possible, based on whether upstream supports gateways.

USDF will require special attention because they currently deploy a separate ingress-nginx service outside of the vCluster_ clusters that are visible to Phalanx environment administrators.
As part of this migration, this practice should stop for Phalanx-managed clusters and the gateway API implementation should be managed by Phalanx as it is in any other Phalanx environment.

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

Envoy
-----

The `Envoy gateway`_ is a controller that implements the Gateway protocol by dynamically configuring the `Envoy proxy`_.
The bare proxy supports everything we need (except auth caching), but the gateway operator does not yet expose all of the necessary config to the Kubernetes API.


.. _Envoy proxy: https://www.envoyproxy.io/
.. _Envoy gateway: https://gateway.envoyproxy.io/docs/

External auth is configured by using the `ext_authz filter <https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter>`__.
This filter enables calling out to either an HTTP or GRPC-based auth server and manipulating the request to the backend and the response to the client based on the response from the auth server.

Both the `gRPC protocol for external auth <https://www.envoyproxy.io/docs/envoy/latest/api-v3/service/auth/v3/external_auth.proto>`__ and the `HTTP configuration <https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto#envoy-v3-api-msg-extensions-filters-http-ext-authz-v3-httpservice>`__ support all of the auth features we need, but the gateway API does not expose all of the necessary config.
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
     - **no** [#]_
   * - Redirect to login
     - **no**
     - **no** [#]_
   * - Cache auth responses
     - **no**
     - **no**

.. [#] Though the whole header passing API in the gateway is currently pretty buggy, as seen in `this GitHub issue <https://github.com/envoyproxy/envoy/issues/41828#issuecomment-3766420747>`__
.. [#] There is a good chance that this will be supported by the gateway in the future, though who knows when.
   `This GitHub comment <https://github.com/envoyproxy/envoy/issues/41828#issuecomment-3766295193>`__ suggests that folks are working on improving the whole external auth API.
   In the meantime, this could maybe be done with `PatchPolicy <https://gateway.envoyproxy.io/docs/tasks/extensibility/envoy-patch-policy/>`__, but not recommended.
.. [#] Gafaelfawr would have to return a 3xx response with the correct location

Envoy supports URL rewriting via the standardized ``HTTPURLRewriteFilter`` approach, which is cleaner than Traefik's use of custom middleware.
This approach is more limited in what it can do, but I believe it will satisfy our requirements.

Envoy appears to be missing the following necessary features:

- Envoy `does not support caching of external authentication results <https://github.com/envoyproxy/envoy/issues/3023>`__.
- There does not appear to be any support for rewriting URLs returned by the backend before sending them to the client.
  We may be able to use `a custom Lua extension <https://gateway.envoyproxy.io/docs/tasks/extensibility/lua/>`__ for this.

Unlike some of the other new gateways, Envoy is written in C++, rather than in a memory-safe language such as Go.
This is not as bad as being written in C, but it somewhat increases the risk of security vulnerabilities.

Kgateway
--------

Kgateway_ is, so far as I can tell, a wrapper around Envoy with a lot of tacked-on AI marketing buzzwords.
It appears to have all of the same tradeoffs as Envoy for Phalanx.
None of the `advantages over Envoy <https://kgateway.dev/docs/envoy/latest/faqs/#whats-the-difference-between-kgateway-and-envoy>`__ appear to be relevant for our use case.

.. _Kgateway: https://kgateway.dev/docs/envoy/latest/about/overview/

The documentation is quite nice and easy to follow, though, so it may be worth a closer look.

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

HAProxy
-------

HAProxy_ has an initial implementation of the Kubernetes Gateway API, but it is appears to be incomplete, largely undocumented, and possibly unmaintained.
I was unable to determine whether it supported any of the features we need.

.. _HAProxy: https://www.haproxy.com/documentation/kubernetes-ingress/gateway-api/

.. _gaps:

Gaps
====

The two main gaps in the available Gateway API implementations appear to be response URL rewriting and caching of external authentication replies.

Response URL rewriting
----------------------

Currently, the Portal and the CADC TAP server both rely on ingress-nginx's ability to rewrite ``Location`` headers in responses from the backend.
This is configured with the ``proxy-redirect-from`` and ``proxy-redirect-to`` annotations.
So far as I can tell, none of the Gateway API implementations support this.

Given that we have contact with and some influence over the implementation of both software packages, we should hopefully be able to eliminate the need for this type of rewriting.
The application needs to take a configuration option specifying the base path for its URLs and use that configuration when constructing URLs in ``Location`` headers.
See, for example, how Argo CD supports this via the ``server.basehref`` and ``server.rootpath`` configuration parameters.

External authentication caching
-------------------------------

Nublado, the Portal, and the Butler server rely on caching of external authentication responses from Gafaelfawr for up to five minutes.
Without this support, every resource request to those services requires a request to Gafaelfawr, which can mean rather high load on Gafaelfawr and on the gateway given the number of resource requests.
For Nublado and Portal, this means an extra request for every JavaScript AJAX request.
For Butler, uncached authorization checks caused noticable performance degredation for common use cases before caching was enabled.

There does not appear to be a straightforward path to resolve this gap.
Neither the Traefik nor the Envoy projects appear interested in adding support, although the Traefik developers did indicate they would look at community PRs.

It might be possible to set up a cache between the gateway and Gafaelfawr, via a separate stand-alone NGINX or Varnish instance or something similar, but this is very unappealing from a complexity standpoint.

We could attempt to optimize the Gafaelfawr request rather than avoid it.
Currently, every authorization check requires a call to Redis.
That call, at least, could be avoided by adding an additional in-memory cache similar to that used in ingress-nginx currently, using the method and the ``Authorization`` and ``Cookie`` headers as keys.
It's not clear whether that would be sufficient to make an approach without gateway-side caching viable, since each request would still have to pay the cost of parsing the Gafaelfawr request in Python.

Using Envoy does open up some additional possibilities since with Envoy the external auth request could be a gRPC request.
We would have to experiment to see if those requests were more efficient; they might be, since the parsing of the request is done via protobuf and should be faster than the Python-based parsing of conventional HTTP query parameters.

In the most extreme case, it may be possible to implement a caching layer for the external authorization check in another, faster programming language (Rust or Go) with gRPC support, and have it call out to the Gafaelfawr Python backend only when needed.
This is a lot of additional complexity, however, and should only be considered if the lack of caching causes unacceptable performance degredation and we can't find a better alternative.

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

