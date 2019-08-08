/// <reference types="Cypress" />

var jwtDecode = require('jwt-decode');

context('Layout assertions', () => {
  beforeEach(() => {
    cy.visit(`${Cypress.config().baseUrl}ui/`)
    // enter valid username and password
    cy.get('[id=email]').type(Cypress.env('username'))
    cy.get('[name=password]').type(Cypress.env('password'))
    cy.contains('button', 'Log in').click().wait(5000)
      .then(() =>
        cy.getCookie('JWT').then(cookie => {
          const userId = jwtDecode(cookie.value).sub
          localStorage.setItem(`${userId}-onboarding`, JSON.stringify({ complete: true }))
          cy.visit('/')
        })
      )

  })

  describe('Overall layout and structure', () => {
    it('shows the left navigation', () => {
      cy.get('.leftFixed.leftNav')
        .should('contain', 'Dashboard')
        .and('contain', 'Devices')
        .and('contain', 'Releases')
        .and('contain', 'Deployments')
        .and('be.visible')
        .end();
    });

    it('has clickable header buttons', () => {
      cy.get('a').contains('Dashboard').click().end()
      cy.get('a').contains('Devices').click().end()
      cy.get('a').contains('Releases').click().end()
      cy.get('a').contains('Deployments').click().end()
    })

    it('can authorize a device', () => {
      cy.get('a').contains('Devices').click().wait(30000).end()
      cy.get('a').contains('Pending').click().end()
      cy.get('.deviceListItem input').click().end()
      cy.get('button').contains('Authorize').click().end()
      cy.get('a').contains('Device groups').click().wait(5000).end()
      
      cy.get('.deviceListItem')
        .should('contain', "qemux86-64")
    })

    it('has basic inventory', () => {
      cy.get('a').contains('Devices').click().end()
      cy.get('div.rightFluid .deviceListItem').click()
        .should('contain', "qemux86-64").end()
      cy.get('.expandedDevice')
        .should('contain', `${Cypress.env('demoDeviceName') || 'mender-image-master'}`)
        .and('contain', 'Linux version')
        .and('contain', 'mac_enp0')
        .and('contain', 'qemux86-64')
    })
  })
})
