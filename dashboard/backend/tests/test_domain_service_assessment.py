from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.domain_service_assessment import (
    SERVICE_CATALOG,
    DnsLookup,
    DomainDnsAssessor,
    is_strict_subdomain,
    parse_spf_record,
)


NOW = datetime(2026, 9, 16, 12, 30, tzinfo=UTC)


class FakeResolver:
    def __init__(self, responses=None, *, default_ttl: int = 3600):
        self.responses = {
            (name.lower().rstrip("."), rdtype.upper()): response
            for (name, rdtype), response in (responses or {}).items()
        }
        self.default_ttl = default_ttl
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, name: str, rdtype: str) -> DnsLookup:
        key = (name.lower().rstrip("."), rdtype.upper())
        self.calls.append(key)
        response = self.responses.get(key)
        if isinstance(response, Exception):
            raise response
        return response or DnsLookup("nodata", ttl_seconds=self.default_ttl)


def answer(*values: str, ttl: int = 3600) -> DnsLookup:
    return DnsLookup("answer", values, ttl)


class PureHelperTests(unittest.TestCase):
    def test_catalog_and_dns_suffix_matching_are_explicit(self) -> None:
        self.assertEqual(SERVICE_CATALOG["microsoft365"]["label"], "Microsoft 365")
        self.assertTrue(is_strict_subdomain(
            "Tenant-Eu.Mail.Protection.Outlook.Com.",
            "mail.protection.outlook.com",
        ))
        for value in (
            "mail.protection.outlook.com",
            "tenant.mail.protection.outlook.com.attacker.example",
            "notmail.protection.outlook.com",
            "https://tenant.mail.protection.outlook.com",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_strict_subdomain(
                    value, "mail.protection.outlook.com",
                ))

    def test_spf_parser_honors_qualifiers_and_unreachable_terms(self) -> None:
        parsed = parse_spf_record(
            "v=spf1 +include:one.example -include:two.example "
            "~include:three.example ?include:four.example -all "
            "include:unreachable.example redirect=redirect.example"
        )
        self.assertEqual(parsed.errors, ())
        self.assertEqual(parsed.dns_lookup_terms, 4)
        self.assertEqual(
            [(item.domain, item.qualifier, item.positive) for item in parsed.references],
            [
                ("one.example", "+", True),
                ("two.example", "-", False),
                ("three.example", "~", False),
                ("four.example", "?", False),
                ("unreachable.example", "+", False),
                ("redirect.example", "+", False),
            ],
        )

    def test_spf_parser_counts_every_dns_triggering_term(self) -> None:
        parsed = parse_spf_record(
            "v=spf1 a a:mail.example/24//64 mx ptr:ptr.example "
            "exists:%{ir}.block.example include:_spf.example "
            "redirect=redirect.example"
        )
        self.assertEqual(parsed.errors, ())
        self.assertEqual(parsed.dns_lookup_terms, 7)
        self.assertEqual(
            [(item.kind, item.domain) for item in parsed.references],
            [
                ("include", "_spf.example"),
                ("redirect", "redirect.example"),
            ],
        )

    def test_spf_parser_ignores_lookup_terms_after_all(self) -> None:
        parsed = parse_spf_record(
            "v=spf1 a -all mx ptr exists:later.example "
            "include:spf.protection.outlook.com "
            "redirect=spf.protection.outlook.com"
        )
        self.assertEqual(parsed.errors, ())
        self.assertEqual(parsed.dns_lookup_terms, 1)
        self.assertTrue(all(not item.reachable for item in parsed.references))

    def test_spf_parser_rejects_unknown_and_malformed_mechanisms(self) -> None:
        examples = (
            ("v=spf1 frobnicate -all", "unknown_mechanism"),
            ("v=spf1 include -all", "invalid_include"),
            ("v=spf1 include:localhost -all", "invalid_include_domain"),
            ("v=spf1 a/33 -all", "invalid_a"),
            ("v=spf1 mx//129 -all", "invalid_mx"),
            ("v=spf1 ip4:999.0.0.1 -all", "invalid_ip4"),
            ("v=spf1 exists: -all", "invalid_exists"),
        )
        for record, error in examples:
            with self.subTest(record=record):
                self.assertIn(error, parse_spf_record(record).errors)

        # RFC 7208 explicitly reserves extension through unknown modifiers.
        extension = parse_spf_record(
            "v=spf1 vendor-feature=value "
            "include:spf.protection.outlook.com -all"
        )
        self.assertEqual(extension.errors, ())
        self.assertEqual(extension.dns_lookup_terms, 1)


class DomainDnsAssessorTests(unittest.IsolatedAsyncioTestCase):
    def assessor(self, responses=None, **kwargs) -> tuple[DomainDnsAssessor, FakeResolver]:
        resolver = FakeResolver(responses)
        return DomainDnsAssessor(
            resolver,
            clock=lambda: NOW,
            **kwargs,
        ), resolver

    async def test_mx_match_is_configured_but_boundary_lookalikes_are_negative(self) -> None:
        assessor, _ = self.assessor({
            ("example.com", "MX"): answer(
                "0 example-com.mail.protection.outlook.com.", ttl=1800,
            ),
        })
        result = await assessor.assess("Example.COM.")
        self.assertEqual(result["dns_status"], "fresh")
        self.assertEqual(result["assessment"], "configured")
        self.assertEqual(result["score"], 0.2)
        self.assertEqual(result["evidence"], [{
            "type": "mx",
            "value": "example-com.mail.protection.outlook.com",
            "rule_id": "microsoft365.mx.exchange_online",
        }])

        for target in (
            "mail.protection.outlook.com",
            "example.mail.protection.outlook.com.attacker.example",
            "example.notmail.protection.outlook.com",
        ):
            with self.subTest(target=target):
                negative, _ = self.assessor({
                    ("example.com", "MX"): answer(target),
                })
                outcome = await negative.assess("example.com")
                self.assertEqual(outcome["dns_status"], "negative")
                self.assertEqual(outcome["assessment"], "unknown")
                self.assertEqual(outcome["evidence"], [])

    async def test_supported_microsoft_cloud_mx_names_are_recognized(self) -> None:
        for target in (
            "tenant.mail.protection.office365.us",
            "tenant.mail.protection.partner.outlook.cn",
            "tenant.o-v1.mx.microsoft",
        ):
            with self.subTest(target=target):
                assessor, _ = self.assessor({
                    ("example.com", "MX"): answer(target),
                })
                result = await assessor.assess("example.com")
                self.assertEqual(result["dns_status"], "fresh")
                self.assertEqual(result["assessment"], "configured")
                self.assertEqual(result["evidence"][0]["value"], target)

    async def test_direct_positive_spf_supports_all_microsoft_clouds(self) -> None:
        examples = (
            ("include:spf.protection.outlook.com", "commercial", "include"),
            ("+include:spf.protection.office365.us", "gcc", "include"),
            ("redirect=spf.protection.partner.outlook.cn", "21vianet", "redirect"),
        )
        for reference, variant, kind in examples:
            with self.subTest(reference=reference):
                suffix = "" if kind == "redirect" else " -all"
                assessor, _ = self.assessor({
                    ("example.com", "TXT"): answer(
                        f"v=spf1 {reference}{suffix}", ttl=900,
                    ),
                })
                result = await assessor.assess("example.com")
                self.assertEqual(result["dns_status"], "fresh")
                self.assertEqual(result["assessment"], "configured")
                self.assertEqual(result["score"], 0.6)
                self.assertEqual(len(result["evidence"]), 1)
                self.assertEqual(result["evidence"][0]["type"], "spf")
                self.assertEqual(
                    result["evidence"][0]["rule_id"],
                    f"microsoft365.spf.{variant}.{kind}.direct",
                )

    async def test_mx_plus_spf_is_strong(self) -> None:
        assessor, _ = self.assessor({
            ("example.com", "MX"): answer(
                "example-com.mail.protection.outlook.com", ttl=1200,
            ),
            ("example.com", "TXT"): answer(
                "v=spf1 include:spf.protection.outlook.com -all", ttl=900,
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["assessment"], "strong")
        self.assertEqual(result["score"], 0.8)

    async def test_transitive_spf_include_and_redirect_are_followed(self) -> None:
        assessor, resolver = self.assessor({
            ("example.com", "TXT"): answer(
                "v=spf1 include:relay.example -all", ttl=1000,
            ),
            ("relay.example", "TXT"): answer(
                "v=spf1 redirect=spf.protection.outlook.com", ttl=800,
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["assessment"], "configured")
        spf = next(item for item in result["evidence"] if item["type"] == "spf")
        self.assertEqual(
            spf["rule_id"],
            "microsoft365.spf.commercial.redirect.transitive",
        )
        self.assertIn(("relay.example", "TXT"), resolver.calls)
        self.assertNotIn(("spf.protection.outlook.com", "TXT"), resolver.calls)

    async def test_nonpositive_or_unreachable_spf_never_configures_service(self) -> None:
        references = (
            "-include:spf.protection.outlook.com",
            "~include:spf.protection.outlook.com",
            "?include:spf.protection.outlook.com",
            "-all include:spf.protection.outlook.com",
            "-all redirect=spf.protection.outlook.com",
        )
        for reference in references:
            with self.subTest(reference=reference):
                assessor, _ = self.assessor({
                    ("example.com", "TXT"): answer(f"v=spf1 {reference}"),
                })
                result = await assessor.assess("example.com")
                self.assertEqual(result["assessment"], "unknown")
                self.assertEqual(result["dns_status"], "negative")
                self.assertEqual(result["evidence"], [])
                self.assertTrue(any(
                    item["rule_id"] == "microsoft365.spf.nonpositive_reference"
                    for item in result["contradictions"]
                ))

    async def test_negative_outer_include_cannot_become_positive_transitively(self) -> None:
        assessor, _ = self.assessor({
            ("example.com", "TXT"): answer(
                "v=spf1 -include:relay.example -all",
            ),
            ("relay.example", "TXT"): answer(
                "v=spf1 include:spf.protection.outlook.com -all",
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["assessment"], "unknown")
        self.assertFalse(result["evidence"])
        self.assertTrue(any(
            item["rule_id"] == "microsoft365.spf.nonpositive_reference"
            for item in result["contradictions"]
        ))

    async def test_multiple_spf_records_are_invalid(self) -> None:
        assessor, _ = self.assessor({
            ("example.com", "TXT"): answer(
                "unrelated verification text",
                "v=spf1 include:spf.protection.outlook.com -all",
                "V=SPF1 include:relay.example -all",
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["dns_status"], "invalid")
        self.assertEqual(result["assessment"], "unknown")
        self.assertTrue(any(
            item["rule_id"] == "spf.multiple_records"
            for item in result["contradictions"]
        ))

    async def test_invalid_spf_cannot_be_rescued_by_valid_mx_evidence(self) -> None:
        assessor, _ = self.assessor({
            ("example.com", "MX"): answer(
                "example-com.mail.protection.outlook.com",
            ),
            ("example.com", "TXT"): answer(
                "v=spf1 include:spf.protection.outlook.com -all",
                "v=spf1 include:relay.example -all",
            ),
        })

        result = await assessor.assess("example.com")

        self.assertEqual(result["dns_status"], "invalid")
        self.assertEqual(result["assessment"], "unknown")
        self.assertTrue(any(
            item["type"] == "mx" for item in result["evidence"]
        ))

    async def test_spf_include_loop_is_invalid_and_each_name_is_queried_once(self) -> None:
        assessor, resolver = self.assessor({
            ("example.com", "TXT"): answer("v=spf1 include:a.example -all"),
            ("a.example", "TXT"): answer("v=spf1 redirect=example.com"),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["dns_status"], "invalid")
        self.assertTrue(any(
            item["rule_id"] == "spf.include_loop"
            for item in result["contradictions"]
        ))
        self.assertEqual(resolver.calls.count(("example.com", "TXT")), 1)
        self.assertEqual(resolver.calls.count(("a.example", "TXT")), 1)

    async def test_spf_dns_lookup_limit_is_enforced_before_eleventh_query(self) -> None:
        responses = {}
        for index in range(11):
            current = "example.com" if index == 0 else f"hop{index}.example"
            following = f"hop{index + 1}.example"
            responses[(current, "TXT")] = answer(
                f"v=spf1 include:{following} -all",
            )
        responses[("hop11.example", "TXT")] = answer(
            "v=spf1 include:spf.protection.outlook.com -all",
        )
        assessor, resolver = self.assessor(responses, max_spf_lookups=10)
        result = await assessor.assess("example.com")
        self.assertEqual(result["dns_status"], "invalid")
        self.assertTrue(any(
            item["rule_id"] == "spf.lookup_limit"
            for item in result["contradictions"]
        ))
        txt_calls = [call for call in resolver.calls if call[1] == "TXT"]
        # The initial policy fetch is not one of RFC 7208's ten terms.  The
        # tenth include can fetch hop10; hop10's eleventh include is rejected.
        self.assertEqual(len(txt_calls), 11)
        self.assertIn(("hop10.example", "TXT"), txt_calls)
        self.assertNotIn(("hop11.example", "TXT"), txt_calls)

    async def test_nonrecursive_dns_terms_share_the_global_lookup_limit(self) -> None:
        allowed, _ = self.assessor({
            ("example.com", "TXT"): answer(
                "v=spf1 " + " ".join(["a"] * 9) +
                " include:spf.protection.outlook.com -all",
            ),
        })
        allowed_result = await allowed.assess("example.com")
        self.assertEqual(allowed_result["dns_status"], "fresh")
        self.assertEqual(allowed_result["assessment"], "configured")

        exceeded, _ = self.assessor({
            ("example.com", "TXT"): answer(
                "v=spf1 " + " ".join(["a"] * 10) +
                " include:spf.protection.outlook.com -all",
            ),
        })
        exceeded_result = await exceeded.assess("example.com")
        self.assertEqual(exceeded_result["dns_status"], "invalid")
        self.assertEqual(exceeded_result["assessment"], "unknown")
        self.assertFalse(exceeded_result["evidence"])
        self.assertTrue(any(
            item["rule_id"] == "spf.lookup_limit"
            for item in exceeded_result["contradictions"]
        ))

    async def test_dns_term_limit_is_global_across_recursive_policies(self) -> None:
        assessor, resolver = self.assessor({
            ("example.com", "TXT"): answer(
                "v=spf1 a a a a a include:relay.example -all",
            ),
            ("relay.example", "TXT"): answer(
                "v=spf1 mx mx mx mx "
                "include:spf.protection.outlook.com -all",
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["dns_status"], "invalid")
        self.assertEqual(result["assessment"], "unknown")
        self.assertFalse(result["evidence"])
        self.assertIn(("relay.example", "TXT"), resolver.calls)
        self.assertNotIn(("spf.protection.outlook.com", "TXT"), resolver.calls)
        self.assertTrue(any(
            item["rule_id"] == "spf.lookup_limit"
            for item in result["contradictions"]
        ))

    async def test_unknown_or_malformed_spf_mechanism_invalidates_assessment(self) -> None:
        for mechanism in (
            "frobnicate",
            "include",
            "a/33",
            "mx//129",
            "ip6:not-an-address",
            "exists:",
        ):
            with self.subTest(mechanism=mechanism):
                assessor, _ = self.assessor({
                    ("example.com", "TXT"): answer(
                        "v=spf1 include:spf.protection.outlook.com "
                        f"{mechanism} -all",
                    ),
                })
                result = await assessor.assess("example.com")
                self.assertEqual(result["dns_status"], "invalid")
                self.assertEqual(result["assessment"], "unknown")
                self.assertFalse(result["evidence"])
                self.assertTrue(any(
                    item["rule_id"].startswith("spf.")
                    for item in result["contradictions"]
                ))

    async def test_both_established_and_new_dkim_namespaces_are_strong(self) -> None:
        assessor, _ = self.assessor({
            ("selector1._domainkey.example.com", "CNAME"): answer(
                "selector1-example-com._domainkey.tenant.onmicrosoft.com.",
            ),
            ("selector2._domainkey.example.com", "CNAME"): answer(
                "selector2-example-com.ab01.dkim.mail.microsoft.",
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["dns_status"], "fresh")
        self.assertEqual(result["assessment"], "strong")
        self.assertEqual(result["score"], 0.5)
        self.assertEqual(
            {item["rule_id"] for item in result["evidence"]},
            {
                "microsoft365.dkim.onmicrosoft.selector1",
                "microsoft365.dkim.mail_microsoft.selector2",
            },
        )

    async def test_dkim_suffix_lookalikes_do_not_match(self) -> None:
        assessor, _ = self.assessor({
            ("selector1._domainkey.example.com", "CNAME"): answer(
                "tenant.onmicrosoft.com.attacker.example",
            ),
            ("selector2._domainkey.example.com", "CNAME"): answer(
                "notdkim.mail.microsoft",
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["dns_status"], "negative")
        self.assertEqual(result["evidence"], [])

    async def test_timeout_and_unexpected_resolver_exception_are_unavailable_not_raised(self) -> None:
        timeout = DnsLookup("timeout")
        assessor, _ = self.assessor({
            ("example.com", "MX"): timeout,
            ("example.com", "TXT"): TimeoutError("private resolver detail"),
            ("selector1._domainkey.example.com", "CNAME"): timeout,
            ("selector2._domainkey.example.com", "CNAME"): timeout,
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["dns_status"], "unavailable")
        self.assertEqual(result["assessment"], "unknown")
        self.assertEqual(result["ttl_seconds"], 0)
        self.assertNotIn("private resolver detail", str(result))
        self.assertTrue(all(
            item["rule_id"].startswith("dns.")
            for item in result["contradictions"]
        ))

    async def test_minimum_dns_ttl_and_assessment_time_are_returned(self) -> None:
        assessor, _ = self.assessor({
            ("example.com", "MX"): answer(
                "example-com.mail.protection.outlook.com", ttl=1800,
            ),
            ("example.com", "TXT"): answer(
                "v=spf1 include:spf.protection.outlook.com -all", ttl=900,
            ),
            ("selector1._domainkey.example.com", "CNAME"): DnsLookup(
                "nodata", ttl_seconds=1200,
            ),
            ("selector2._domainkey.example.com", "CNAME"): DnsLookup(
                "nxdomain", ttl_seconds=1500,
            ),
        })
        result = await assessor.assess("example.com")
        self.assertEqual(result["ttl_seconds"], 900)
        self.assertEqual(result["assessed_at"], NOW.isoformat())
        self.assertEqual(result["assessment"], "strong")

    async def test_invalid_domain_is_categorized_without_dns_queries(self) -> None:
        assessor, resolver = self.assessor()
        result = await assessor.assess(
            "example.com.attacker.invalid/path",
        )
        self.assertEqual(result["dns_status"], "invalid")
        self.assertEqual(result["assessment"], "unknown")
        self.assertEqual(result["ttl_seconds"], 0)
        self.assertEqual(resolver.calls, [])
        self.assertEqual(result["contradictions"][0]["rule_id"], "dns.invalid_domain")


if __name__ == "__main__":
    unittest.main()
