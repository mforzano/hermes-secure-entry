"""Agent-selected backend nodes, real disposable Chrome and CapturedCDP."""
import unittest
from playwright.sync_api import Error as PlaywrightError
import test_payment_browser as fixtures
from secure_entry.payment_browser import Target, BindingRefused

CARD = dict(number='4242424242424242', exp_month=12, exp_year=2035,
            cvc='987', billing_address={'name':'Synthetic Cardholder','postal_code':'10001'})


class MappingTests(unittest.TestCase):
    setUp = fixtures.PaymentBrowserTests.setUp
    cleanup = fixtures.PaymentBrowserTests.cleanup

    def mapping(self, html=None, selectors=None, frame=None):
        frame = frame or self.page.frames[1]
        if html is not None:
            frame.evaluate('html=>document.body.innerHTML=html', html)
        try:
            session = self.context.new_cdp_session(frame)
            context = None
        except PlaywrightError:
            session = self.context.new_cdp_session(self.page)
            context = session.send('Page.createIsolatedWorld',dict(frameId=self.frame,worldName='synthetic-inspection'))['executionContextId']
        result = {}
        import json
        for token, selector in selectors or [('cc-number','#pan'),('cc-exp-month','#month'),
                                ('cc-exp-year','#year'),('cc-csc','#cvc'),('cc-name','#name')]:
            params={'expression':'document.querySelector('+json.dumps(selector)+')'}
            if context is not None:
                params['contextId']=context
            obj=session.send('Runtime.evaluate',params)['result']['objectId']
            result[token] = session.send('DOM.describeNode',dict(objectId=obj))['node']['backendNodeId']
            session.send('Runtime.releaseObject',dict(objectId=obj))
        session.detach()
        return result

    @staticmethod
    def html():
        return '''<form><input id="pan" value="old pan"><input id="month" type="tel">
          <input id="year" type="tel"><input id="cvc" autocomplete="cc-cvc">
          <input id="name" autocomplete="name" value="Guest Name"><input id="billing" value="Guest address">
          <input type="checkbox" id="tos"><input name="unknown"><textarea></textarea></form>
          <form><input autocomplete="cc-number" id="other"><input type="password"></form>'''

    def target(self, mapping):
        target = Target(self.capture,self.parent,self.frame,'https://merchant.test',
                        'https://provider.test',lambda:None,field_mapping=mapping)
        self.addCleanup(target.close)
        return target

    _run_facility = fixtures.PaymentBrowserTests._run_facility

    def test_registered_link_mapping_with_genuine_consent(self):
        mapping = self.mapping(self.html())
        result, prompts = self._run_facility(field_mapping=mapping, issued_card=CARD, registered=True)
        self.assertTrue(result.get('success'), result)
        self.assertEqual(result['filled_fields'],5)
        self.assertIn('cc-number',str(prompts))
        self.assertNotIn(CARD['number'],str(prompts)+str(result))

    def test_registered_link_noop_target_attributes_during_consent(self):
        mapping = self.mapping(self.html())
        def rewrite():
            self.page.frames[1].evaluate('''()=>{
                for(const e of document.querySelectorAll('input')){
                    e.setAttribute('type',e.type);e.setAttribute('name',e.name);e.removeAttribute('form');
                }
            }''')
            # Establish explicit attribute values before the retained snapshot.
        rewrite()
        result, _ = self._run_facility(field_mapping=mapping, issued_card=CARD,
                                      registered=True, before_answer=lambda: [rewrite() for _ in range(5)])
        self.assertTrue(result.get('success'), result)
        self.assertEqual(result['filled_fields'],5)

    def test_registered_saved_card_mapping_genuine_native_vault_consent(self):
        self.saved_card_fill()

    def saved_card_fill(self, before_answer=None):
        import json
        from test_cards import CardTests
        from tools import approval
        from hermes_cli.plugins import PluginContext,PluginManifest,get_plugin_manager
        fixture=CardTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        handle=fixture.save_card()
        mapping=self.mapping(self.html())
        self.page.frames[1].evaluate('''()=>{
            for(const e of document.querySelectorAll('input')){
                e.setAttribute('type',e.type);e.setAttribute('name',e.name);
            }
        }''')
        prompts=[]
        def notify(data):
            prompts.append(data)
            if before_answer:
                before_answer()
            approval.resolve_gateway_approval('synthetic-key','once',request_id=data['request_id'])
        approval.register_gateway_notify('synthetic-key',notify)
        self.addCleanup(approval.unregister_gateway_notify,'synthetic-key')
        ctx=PluginContext(PluginManifest(name='synthetic-mapped-card'),get_plugin_manager())
        registration=ctx.register_tool(name='secure_entry_card_fill',toolset='secure_entry',
            schema={'name':'secure_entry_card_fill','parameters':{'type':'object'}},
            handler=fixture.service.selected_card_fill)
        self.addCleanup(registration.dispose)
        result=json.loads(ctx.dispatch_tool('secure_entry_card_fill',dict(handle=handle,
            parent=self.parent,frame=self.frame,merchant_origin='https://merchant.test',
            frame_origin='https://provider.test',field_mapping=mapping),task_id='synthetic-payment'))
        self.assertTrue(result.get('success'),result)
        self.assertEqual(result['filled_fields'],5)
        self.assertEqual(len(prompts),1)
        self.assertTrue(self.page.frames[1].evaluate("document.querySelector('#name').value==='SYNTHETIC CARDHOLDER'"))
        self.assertIsNotNone(fixture.store.get_meta(handle))
        self.assertNotIn(CARD['number'],str(prompts)+str(result))

    def test_registered_saved_card_presentation_mutations_during_consent(self):
        def rewrite():
            self.page.frames[1].evaluate('''()=>{
                for(let i=0;i<5;i++)for(const e of document.querySelectorAll('input')){
                    e.setAttribute('type',e.type);e.setAttribute('name',e.name);e.removeAttribute('form');
                }
            }''')
            self.page.evaluate('''()=>{
                for(let i=0;i<5;i++){
                    const e=document.querySelector('iframe');
                    e.setAttribute('frameborder','0');e.className='widget-'+i;
                    e.parentElement.className='layout-'+i;
                    e.parentElement.setAttribute('data-status','ready-'+i);
                    e.style.borderWidth=i+'px';
                }
            }''')
        self.saved_card_fill(before_answer=rewrite)

    def test_combined_mask_react_setter_and_explicit_billing_select(self):
        html='''<div><input id="pan"><input id="expiry"><select id="country"><option value="US">United States</option></select>
            <input id="name" value="Guest"><input id="address" value="Guest address"></div>'''
        mapping=self.mapping(html,[('cc-number','#pan'),('cc-exp','#expiry'),('cc-name','#name'),('billing country','#country')])
        self.page.frames[1].evaluate('''()=>{
            const pan=document.querySelector('#pan'), expiry=document.querySelector('#expiry');
            let tracked='';Object.defineProperty(pan,'value',{configurable:true,get(){return HTMLInputElement.prototype.__lookupGetter__('value').call(this)},set(v){tracked=v}});
            pan.addEventListener('input',()=>{document.body.dataset.reactAccepted=String(pan.value!==tracked)});
            expiry.oninput=()=>expiry.value=expiry.value.replace('/',' / ');
        }''')
        result=self.target(mapping).fill({**CARD,'billing_address':{'name':'Synthetic Cardholder','country':'US'}})
        self.assertEqual(result['filled_fields'],4)
        self.assertTrue(self.page.frames[1].evaluate('''()=>document.body.dataset.reactAccepted==='true' &&
            document.querySelector('#expiry').value==='12 / 35' && document.querySelector('#address').value==='Guest address' '''))

    def test_standalone_root_with_no_form_or_autocomplete(self):
        session=self.context.new_cdp_session(self.page)
        root=session.send('Page.getFrameTree')['frameTree']['frame']['id']
        session.detach()
        mapping=self.mapping(self.html(),frame=self.page.main_frame)
        target=Target(self.capture,self.parent,root,'https://merchant.test','https://merchant.test',lambda:None,field_mapping=mapping)
        self.addCleanup(target.close)
        self.assertEqual(target.fill(CARD)['filled_fields'],5)
        self.assertTrue(self.page.evaluate("document.querySelector('#pan').value==='4242424242424242'"))

    def test_separate_expiry_selects_and_two_digit_year_input(self):
        for year in ['<select id="year"><option value="35">2035</option></select>', '<input id="year" maxlength="2">']:
            html='<div><input id="pan"><select id="month"><option value="12">December</option></select>'+year+'<input id="cvc"><input id="name"></div>'
            mapping=self.mapping(html)
            target=self.target(mapping)
            self.assertEqual(target.fill(CARD)['filled_fields'],5)
            self.assertTrue(self.page.frames[1].evaluate("document.querySelector('#year').value==='35'"))
            target.close()

    def test_registered_same_origin_iframe_observed_checkout_shape(self):
        html='''<form id="payment-submit-form">
            <input id="pan" type="tel" autocomplete="cc-number"><input id="month" type="tel" autocomplete="cc-exp-month">
            <input id="year" type="tel" autocomplete="cc-exp-year"><input id="cvc" type="tel" autocomplete="cc-cvc">
            <input id="name" autocomplete="name" value="Guest Name"><input autocomplete="address-line1" value="Guest address">
            <input autocomplete="address-line2"><input autocomplete="address-level2" value="Guest City">
            <input autocomplete="postal-code" value="10001"><select autocomplete="country-name"><option value="US">United States</option></select>
            <input id="state"><select id="phone-country-code"><option value="1">+1</option></select><input type="tel" autocomplete="on">
            </form><input type="checkbox" id="tos"><input type="checkbox" id="email_opt_out">'''
        self.context.route('https://merchant.test/payment-fixture',lambda r:r.fulfill(content_type='text/html',body=html))
        self.page.locator('iframe').evaluate("e=>e.src='https://merchant.test/payment-fixture'")
        self.page.frames[1].wait_for_url('https://merchant.test/payment-fixture')
        self.page.frames[1].wait_for_load_state()
        session=self.context.new_cdp_session(self.page)
        root=session.send('DOM.getDocument')['root']['nodeId']
        node=session.send('DOM.querySelector',dict(nodeId=root,selector='iframe'))['nodeId']
        self.frame=session.send('DOM.describeNode',dict(nodeId=node))['node']['frameId']
        session.detach()
        mapping=self.mapping()
        result,_=self._run_facility(field_mapping=mapping,issued_card=CARD,registered=True,
                                    frame_origin='https://merchant.test')
        self.assertTrue(result.get('success'),result)
        self.assertEqual(result['filled_fields'],5)
        self.assertTrue(self.page.frames[1].evaluate('''()=>document.querySelector('[autocomplete="address-line1"]').value==='Guest address' &&
            !document.querySelector('#tos').checked && !document.querySelector('#email_opt_out').checked'''))

    def test_missing_explicit_billing_refuses_without_filling_card(self):
        from secure_entry.payment_browser import WriteRefused
        mapping=self.mapping(self.html())
        mapping['billing address-line1']=mapping.pop('cc-name')
        with self.assertRaises(WriteRefused) as failure:
            self.target(mapping).fill(CARD)
        self.assertEqual(failure.exception.category,'source_missing')
        self.assertEqual(failure.exception.written,0)
        self.assertTrue(self.page.frames[1].evaluate("document.querySelector('#pan').value==='old pan'"))

    def test_rejected_framework_value_is_not_counted_as_filled(self):
        from secure_entry.payment_browser import WriteRefused
        mapping=self.mapping(self.html())
        self.page.frames[1].evaluate("()=>document.querySelector('#pan').oninput=e=>e.target.value=''")
        with self.assertRaises(WriteRefused) as failure:
            self.target(mapping).fill(CARD)
        self.assertEqual(failure.exception.category,'write_mismatch')
        self.assertEqual(failure.exception.written,0)

    def test_unknown_foreign_and_nonfield_nodes_are_refused(self):
        # backendNodeIds are renderer-scoped: an OOPIF's numeric ID can collide
        # with a valid child input. Use two documents in the same renderer so
        # this negative fixture actually names the foreign node, not an alias.
        self.context.route('https://merchant.test/foreign-node-fixture',
            lambda r:r.fulfill(content_type='text/html',body=self.html()))
        self.page.locator('iframe').evaluate("e=>e.src='https://merchant.test/foreign-node-fixture'")
        self.page.frames[1].wait_for_url('https://merchant.test/foreign-node-fixture')
        self.page.frames[1].wait_for_load_state()
        session=self.context.new_cdp_session(self.page)
        root=session.send('DOM.getDocument')['root']['nodeId']
        node=session.send('DOM.querySelector',dict(nodeId=root,selector='iframe'))['nodeId']
        self.frame=session.send('DOM.describeNode',dict(nodeId=node))['node']['frameId']
        session.detach()
        mapping = self.mapping()
        def same_origin_target(selected):
            target = Target(self.capture,self.parent,self.frame,'https://merchant.test',
                            'https://merchant.test',lambda:None,field_mapping=selected)
            self.addCleanup(target.close)
            return target
        parent_session = self.context.new_cdp_session(self.page)
        self.page.evaluate("()=>{const e=document.createElement('input');e.id='foreign-input';document.body.append(e)}")
        root = parent_session.send('DOM.getDocument')['root']['nodeId']
        iframe = parent_session.send('DOM.querySelector',dict(nodeId=root,selector='#foreign-input'))['nodeId']
        foreign = parent_session.send('DOM.describeNode',dict(nodeId=iframe))['node']['backendNodeId']
        parent_session.detach()
        body = self.mapping(selectors=[('body','body')])['body']
        for invalid in [2147483647, foreign, body, True, '12', -1]:
            with self.subTest(kind=type(invalid).__name__,invalid=invalid):
                with self.assertRaises(BindingRefused):
                    same_origin_target({**mapping,'cc-number':invalid})

    def test_replaced_selected_node_is_not_retargeted(self):
        mapping = self.mapping(self.html())
        target = self.target(mapping)
        self.page.frames[1].evaluate('''()=>{const e=document.querySelector('#pan');
            e.replaceWith(e.cloneNode());}''')
        with self.assertRaises(ValueError):
            target.fill(CARD)
        self.assertTrue(self.page.frames[1].evaluate("document.querySelector('#pan').value==='old pan'"))

    def test_mapping_replacement_during_consent_refuses_before_producer(self):
        mapping = self.mapping(self.html())
        def replace():
            self.page.frames[1].evaluate('''()=>{const e=document.querySelector('#pan');e.replaceWith(e.cloneNode());}''')
        result, _ = self._run_facility(field_mapping=mapping, issued_card=CARD,
                                      registered=True,before_answer=replace)
        self.assertFalse(result['success'])
        self.assertEqual(result['stage'],'postconsent_target')
        self.assertTrue(result.get('reinspection_required'))

    def test_actual_target_authority_changes_remain_sticky_during_consent(self):
        mutations = [
            "const e=document.querySelector('#pan');e.type='password';e.type='text'",
            "const e=document.querySelector('#pan');e.setAttribute('form','other');e.removeAttribute('form')",
            "const e=document.querySelector('#pan'),p=e.parentNode;p.removeChild(e);p.append(e)",
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                mapping=self.mapping(self.html())
                result,_=self._run_facility(field_mapping=mapping,issued_card=CARD,
                    registered=True,before_answer=lambda:self.page.frames[1].evaluate('()=>{'+mutation+'}'))
                self.assertFalse(result['success'])
                self.assertEqual(result['stage'],'postconsent_target')
                self.assertTrue(self.page.frames[1].evaluate("document.querySelector('#pan').value==='old pan'"))

    def test_mapped_iframe_destination_change_restore_is_sticky(self):
        mapping=self.mapping(self.html())
        target=self.target(mapping)
        self.page.evaluate('''()=>{const e=document.querySelector('iframe');
            const src=e.getAttribute('src');e.setAttribute('src','https://foreign.test/pay');e.setAttribute('src',src);}''')
        with self.assertRaises(ValueError):
            target.check()

    def test_explicit_fields_override_prefill_and_ignore_unrelated_layout(self):
        mapping = self.mapping(self.html())
        target = self.target(mapping)
        self.page.frames[1].evaluate('''()=>{document.forms[1].append(document.createElement('input'));
            document.querySelector('#tos').checked=true;
            document.querySelector('#billing').value='Changed guest address';}''')
        result = target.fill(CARD)
        self.assertEqual(result['filled_fields'],5)
        self.assertTrue(self.page.frames[1].evaluate('''()=>
            document.querySelector('#pan').value==='4242424242424242' &&
            document.querySelector('#name').value==='Synthetic Cardholder' &&
            document.querySelector('#billing').value==='Changed guest address' &&
            document.querySelector('#other').value==='' && document.querySelector('#tos').checked'''))


if __name__ == '__main__':
    unittest.main()
