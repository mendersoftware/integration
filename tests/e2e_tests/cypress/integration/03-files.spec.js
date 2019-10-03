/// <reference types="Cypress" />

import 'cypress-file-upload';

context('Files', () => {
  beforeEach(() => {
    cy.visit(`${Cypress.config().baseUrl}ui/`)
    // enter valid username and password
    cy.get('[id=email]').type(Cypress.env('username'))
    cy.get('[name=password]').type(Cypress.env('password'))
    cy.contains('button', 'Log in').click().wait(3000)
    cy.visit('ui/#/releases')
  })

  it('allows file uploads', () => {
    // create an artifact to download first
    const encoding = 'base64'
    const fileName = 'mender-demo-artifact.mender'
    cy.readFile(fileName, encoding).then(fileContent => {
      cy.get('.dropzone input')
        .upload({ fileContent, fileName, encoding, mimeType: 'application/octet-stream' })
        .wait(10000) // give some extra time for the upload
    })
  })

  // it('allows uploading custom file creations', () => {
  //   cy.exec('mender-artifact write rootfs-image -f core-image-full-cmdline-qemux86-64.ext4 -t qemux86-64 -n release1 -o qemux86-64_release_1.mender')
  //     .then(result => {
  //       expect(result.code).to.be.equal(0)
  //         const encoding = 'base64'
  //         const fileName = 'qemux86-64_release_1.mender'
  //         cy.readFile(fileName, encoding).then(fileContent => {
  //           cy.get('.dropzone input')
  //             .upload({ fileContent, fileName, encoding, mimeType: 'application/octet-stream' })
  //             .wait(10000) // give some extra time for the upload
  //         })
  //       })
  // })

  it('allows artifact downloads', () => {
    // TODO allow download in tests, for reference: https://github.com/cypress-io/cypress/issues/949
    cy.get('.expandButton').click().end()
    cy.get('.release-repo-item a').contains('Download Artifact')
      // .click().then(anchor => {
      //   const url = anchor.attr('href');
      //   cy.request(url).then(response => 
      //     cy.writeFile('tempArtifact', response.body)
      //   )
      // })
  })
})


context('Deployments', () => {
  beforeEach(() => {
    cy.visit(`${Cypress.config().baseUrl}ui/`)
    // enter valid username and password
    cy.get('[id=email]').type(Cypress.env('username'))
    cy.get('[name=password]').type(Cypress.env('password'))
    cy.contains('button', 'Log in').click().wait(2000)
    cy.visit('ui/#/devices').wait(3000)
    cy.visit('ui/#/releases').wait(2000)
  })

  it('allows shortcut deployments', () => {
    // create an artifact to download first
    cy.get('.repository-list-item').contains('mender-demo-artifact').click().end()
    cy.get('a').contains('Create deployment').click({ force: true }).wait(5000).end()
    cy.get('[placeholder="Select a device group to deploy to"]').click({ force: true })
    cy.get('[role="tooltip"]').get('li').contains('All devices').click().wait(2000).end()
    cy.get('button').contains('Next').click().end()
    cy.get('.MuiDialog-container button').contains('Create').click().wait(30000).end()
    cy.get('[role="tab"]').contains('Finished').click().end()
    cy.get('tr').get('time').should($elems => {
      const time = Cypress.moment($elems[0].getAttribute("datetime"))
      let earlier = Cypress.moment().subtract(5, 'minutes')
      const now = Cypress.moment()
      expect(time.isBetween(earlier, now))
    })
  })
})

